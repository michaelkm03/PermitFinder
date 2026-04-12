"""
Builds a trail graph from permit site data and OSM trail data.

Graph definition
----------------
  Node  = one permit site (campsite) identified by its rec.gov division_id.
  Edge  = two sites are directly connected by a named OSM hiking trail
          with no other permit site between them on that trail.

Two types of edges
------------------
  Within-trail edge:
      Both sites snap to the same trail polyline. The consecutive pair
      (no other site between them on that trail) is always a valid edge —
      a hiker walks directly from one site to the next along the trail.

  Cross-trail edge:
      Sites on different trails meet at a shared OSM node (a trail junction).
      Validity depends on the trailhead flag (see below).

Trailhead connection definition
--------------------------------
A cross-trail connection is a *trailhead connection* when the shared OSM node
is an endpoint (first or last node) of BOTH trails. That means both trails
start or end at the same parking lot / road access point. A hiker at that node
has exited the trail system and would need to cross a parking lot to reach the
other trail.

It is NOT a trailhead connection when the shared node is an endpoint of only
one trail (a spur branching off a main trail mid-route). The hiker reaches the
junction naturally while hiking the main trail and can turn onto the spur
without leaving the trail system.

--trailhead flag
-----------------
  False (default) : trailhead connections are excluded from the graph.
  True            : trailhead connections are included (useful for routes
                    that intentionally exit and re-enter at a trailhead).

Snap threshold
--------------
A site must be within 0.002 degrees (~200 m at 47–49 °N) of a trail to snap
onto it. This tolerates minor GPS imprecision in the rec.gov coordinates.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import LineString, Point

log = logging.getLogger(__name__)

# ~200 m expressed in degrees at Washington State latitudes.
_SNAP_THRESHOLD_DEGREES = 0.002


@dataclass
class Site:
    division_id: str
    name: str
    lat: float
    lon: float
    district: str


@dataclass
class TrailGraph:
    # All permit sites in the park, keyed by division_id.
    sites: dict[str, Site]
    # Adjacency list: division_id → sorted list of adjacent division_ids.
    adjacency: dict[str, list[str]]


def build_graph(
    raw_sites: list[dict],
    raw_trails: list[dict],
    allow_trailhead: bool = False,
) -> TrailGraph:
    """
    Build a trail graph from raw API data.

    raw_sites       : output of api.fetch_sites() or mock.fetch_sites()
    raw_trails      : output of api.fetch_trails() or mock.fetch_trails()
    allow_trailhead : when True, also connect sites at shared trailhead nodes
                      (parking lots where separatere trails begin / end).
    """
    t0 = time.perf_counter()
    log.debug("build_graph  %d raw sites, %d trails, allow_trailhead=%s",
              len(raw_sites), len(raw_trails), allow_trailhead)

    _site_fields = {f.name for f in Site.__dataclass_fields__.values()}
    # Group sites (shared campsites) are excluded from chain search — a solo/small-group
    # backpacker cannot route through a group-reserved site. fetch_sites() already
    # removes "(No Campfires)" group sites; here we remove remaining regular group sites.
    sites = {
        s["division_id"]: Site(**{k: v for k, v in s.items() if k in _site_fields})
        for s in raw_sites
        if "Group" not in s.get("name", "") and "group" not in s.get("name", "")
    }
    log.debug("build_graph  group-site filter: %d → %d nodes (%d removed)",
              len(raw_sites), len(sites), len(raw_sites) - len(sites))

    # Use sets during construction to avoid duplicate edges, then convert to
    # sorted lists so the adjacency order is deterministic across runs.
    adjacency: dict[str, set[str]] = {div_id: set() for div_id in sites}

    # Step 1 — within-trail edges (always valid).
    t1 = time.perf_counter()
    for raw_trail in raw_trails:
        _add_within_trail_edges(raw_trail, sites, adjacency)
    within_edges = sum(len(v) for v in adjacency.values()) // 2
    log.debug("build_graph  within-trail edges: %d edges from %d trails  (%.3fs)",
              within_edges, len(raw_trails), time.perf_counter() - t1)

    # Step 2 — cross-trail edges at shared OSM nodes (trailhead flag applies).
    t2 = time.perf_counter()
    _add_cross_trail_edges(raw_trails, sites, adjacency, allow_trailhead)
    total_edges = sum(len(v) for v in adjacency.values()) // 2
    log.debug("build_graph  cross-trail edges: %d edges added  (%.3fs)",
              total_edges - within_edges, time.perf_counter() - t2)

    isolated = sum(1 for v in adjacency.values() if not v)
    log.debug("build_graph  done: %d nodes, %d edges, %d isolated  (%.3fs total)",
              len(sites), total_edges, isolated, time.perf_counter() - t0)

    return TrailGraph(
        sites=sites,
        adjacency={div_id: sorted(neighbors) for div_id, neighbors in adjacency.items()},
    )


# ---------------------------------------------------------------------------
# Step 1: within-trail edges
# ---------------------------------------------------------------------------

def _add_within_trail_edges(
    raw_trail: dict,
    sites: dict[str, Site],
    adjacency: dict[str, set[str]],
) -> None:
    """
    Snap all sites to one trail polyline, sort by position, and connect
    each consecutive pair.

    Within-trail edges are always valid — a hiker moves directly from
    one site to the next along the continuous trail without any gap or
    trailhead crossing.
    """
    # Shapely uses (x=lon, y=lat) convention.
    line = LineString([(lon, lat) for lat, lon in raw_trail["points"]])

    # Collect (position_along_line, division_id) for every site on this trail.
    snapped: list[tuple[float, str]] = []

    for div_id, site in sites.items():
        site_point = Point(site.lon, site.lat)
        if line.distance(site_point) > _SNAP_THRESHOLD_DEGREES:
            continue  # site is not on this trail
        position = line.project(site_point)
        snapped.append((position, div_id))

    if len(snapped) < 2:
        return  # need at least 2 sites to form an edge

    snapped.sort()  # sort by ascending position along the trail

    for i in range(len(snapped) - 1):
        _, id_a = snapped[i]
        _, id_b = snapped[i + 1]
        adjacency[id_a].add(id_b)
        adjacency[id_b].add(id_a)


# ---------------------------------------------------------------------------
# Step 2: cross-trail edges
# ---------------------------------------------------------------------------

def _add_cross_trail_edges(
    raw_trails: list[dict],
    sites: dict[str, Site],
    adjacency: dict[str, set[str]],
    allow_trailhead: bool,
) -> None:
    """
    For each pair of trails sharing an OSM node, connect the sites immediately
    adjacent to the junction on each trail.

    No camp sits physically at a junction node — instead, find the last snapped
    site before the junction's position and the first after it on each trail,
    and connect every such site on trail A with every such site on trail B.

    A shared node is a trailhead connection when it is an endpoint of BOTH
    trails (same parking lot). If only one trail treats it as an endpoint, it
    is a genuine junction and is always included.
    """
    # Pre-compute snapped-site positions for each trail.
    # trail_info[osm_id] = {"line", "endpoint_nodes", "node_ids", "points", "snapped"}
    # snapped is a sorted list of (position_along_line, division_id).
    trail_info: dict[str, dict] = {}
    for raw_trail in raw_trails:
        osm_id = raw_trail["osm_id"]
        line = LineString([(lon, lat) for lat, lon in raw_trail["points"]])
        snapped: list[tuple[float, str]] = []
        for div_id, site in sites.items():
            if line.distance(Point(site.lon, site.lat)) <= _SNAP_THRESHOLD_DEGREES:
                pos = line.project(Point(site.lon, site.lat))
                snapped.append((pos, div_id))
        snapped.sort()
        trail_info[osm_id] = {
            "line": line,
            "endpoint_nodes": {raw_trail["node_ids"][0], raw_trail["node_ids"][-1]},
            "node_ids": raw_trail["node_ids"],
            "points": raw_trail["points"],
            "snapped": snapped,
        }

    # Check every pair of trails for shared OSM nodes.
    for trail_a, trail_b in combinations(raw_trails, 2):
        osm_a = trail_a["osm_id"]
        osm_b = trail_b["osm_id"]
        info_a = trail_info[osm_a]
        info_b = trail_info[osm_b]

        shared_nodes = set(trail_a["node_ids"]) & set(trail_b["node_ids"])
        if not shared_nodes:
            continue

        for shared_node in shared_nodes:
            ep_a = shared_node in info_a["endpoint_nodes"]
            ep_b = shared_node in info_b["endpoint_nodes"]
            if ep_a and ep_b and not allow_trailhead:
                continue  # parking-lot trailhead — excluded per --trailhead flag

            # Project the junction's coordinates onto each trail.
            node_idx = info_a["node_ids"].index(shared_node)
            junction_lat, junction_lon = info_a["points"][node_idx]
            junc_pos_a = info_a["line"].project(Point(junction_lon, junction_lat))
            junc_pos_b = info_b["line"].project(Point(junction_lon, junction_lat))

            # Sites immediately flanking the junction on each trail.
            neighbors_a = _sites_adjacent_to_junction(info_a["snapped"], junc_pos_a)
            neighbors_b = _sites_adjacent_to_junction(info_b["snapped"], junc_pos_b)

            for id_a in neighbors_a:
                for id_b in neighbors_b:
                    if id_a != id_b:
                        adjacency[id_a].add(id_b)
                        adjacency[id_b].add(id_a)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _sites_adjacent_to_junction(
    snapped: list[tuple[float, str]],
    junction_pos: float,
) -> list[str]:
    """
    Return the sites immediately before and after junction_pos on this trail.

    'Before' = snapped site with the largest position <= junction_pos.
    'After'  = snapped site with the smallest position >  junction_pos.
    """
    before: str | None = None
    after: str | None = None
    for pos, div_id in snapped:  # sorted ascending
        if pos <= junction_pos:
            before = div_id
        elif after is None:
            after = div_id
            break
    return [d for d in (before, after) if d is not None]
