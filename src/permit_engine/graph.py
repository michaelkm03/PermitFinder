"""
Builds a trail graph from permit site data and OSM trail geometry.

Graph definition
----------------
  Node  = one permit site (campsite) identified by its rec.gov division_id.
  Edge  = two sites are directly connected by a named OSM hiking trail
          with no other permit site between them on that trail.

Adjacency source
----------------
Trail geometry comes from the OpenStreetMap Overpass API (cached 30 days).
Each site is snapped to the nearest point on a trail polyline. Sites within
_SNAP_THRESHOLD_DEGREES of a trail are placed on it; their order along the
trail determines which consecutive pairs become graph edges.

Sites whose rec.gov coordinates are (0, 0) (no GPS data) are added to the
graph as isolated nodes — they can never form a chain but appear in output.

Two types of edges
------------------
  Within-trail edge:
      Both sites snap to the same trail polyline. The consecutive pair
      (no other site between them on that trail) is always a valid edge.

  Cross-trail edge:
      Sites on different trails meet at a shared OSM node (a trail junction).
      Validity depends on the trailhead flag (see below).

Trailhead connection definition
--------------------------------
A cross-trail connection is a *trailhead connection* when the shared OSM node
is an endpoint (first or last node) of BOTH trails — both trails start or end
at the same parking lot. A hiker must leave the trail system to cross it.

It is NOT a trailhead connection when the shared node is an endpoint of only
one trail (a spur branching off a main trail mid-route).

--trailhead flag
-----------------
  False (default) : trailhead connections are excluded.
  True            : trailhead connections are included.

Snap threshold
--------------
A site must be within _SNAP_THRESHOLD_DEGREES (~200 m at WA latitudes) of a
trail polyline to snap onto it. Sites with missing GPS (lat=0, lon=0) are
never snapped and remain isolated.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import LineString, Point

log = logging.getLogger(__name__)

# ~200 m expressed in degrees at Washington State latitudes (47–49 °N).
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
    allow_trailhead : when True, also connect sites at shared trailhead nodes.
    """
    t0 = time.perf_counter()
    log.debug("build_graph  %d raw sites, %d trails, allow_trailhead=%s",
              len(raw_sites), len(raw_trails), allow_trailhead)

    # Exclude group campsites — not usable by solo/small-group backpackers.
    sites: dict[str, Site] = {}
    no_coords: list[str] = []
    for s in raw_sites:
        name = s.get("name", "")
        if "Group" in name or "group" in name:
            log.debug("  skip group site  %s  %r", s["division_id"], name)
            continue
        lat = float(s.get("lat", 0) or 0)
        lon = float(s.get("lon", 0) or 0)
        sites[s["division_id"]] = Site(
            division_id=s["division_id"],
            name=name,
            lat=lat,
            lon=lon,
            district=s.get("district", ""),
        )
        if lat == 0 or lon == 0:
            no_coords.append(s["division_id"])

    log.debug("build_graph  %d nodes (%d group removed, %d missing GPS → isolated)",
              len(sites), len(raw_sites) - len(sites), len(no_coords))

    adjacency: dict[str, set[str]] = {div_id: set() for div_id in sites}

    # Only snap sites that have valid coordinates.
    snappable = {div_id: site for div_id, site in sites.items()
                 if site.lat != 0 and site.lon != 0}

    # Step 1 — within-trail edges (always valid).
    t1 = time.perf_counter()
    for raw_trail in raw_trails:
        _add_within_trail_edges(raw_trail, snappable, adjacency)
    within_edges = sum(len(v) for v in adjacency.values()) // 2
    log.debug("build_graph  within-trail edges: %d  (%.3fs)",
              within_edges, time.perf_counter() - t1)

    # Step 2 — cross-trail edges at shared OSM nodes.
    t2 = time.perf_counter()
    _add_cross_trail_edges(raw_trails, snappable, adjacency, allow_trailhead)
    total_edges = sum(len(v) for v in adjacency.values()) // 2
    log.debug("build_graph  cross-trail edges added: %d  (%.3fs)",
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
    Snap sites to a trail polyline, sort by position, connect consecutive pairs.
    """
    # Shapely uses (x=lon, y=lat) convention.
    line = LineString([(lon, lat) for lat, lon in raw_trail["points"]])

    snapped: list[tuple[float, str]] = []
    for div_id, site in sites.items():
        site_point = Point(site.lon, site.lat)
        if line.distance(site_point) > _SNAP_THRESHOLD_DEGREES:
            continue
        position = line.project(site_point)
        snapped.append((position, div_id))

    if len(snapped) < 2:
        return

    snapped.sort()
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
    adjacent to that junction on each trail.
    """
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
                continue  # parking-lot trailhead — excluded

            node_idx = info_a["node_ids"].index(shared_node)
            junction_lat, junction_lon = info_a["points"][node_idx]
            junc_pos_a = info_a["line"].project(Point(junction_lon, junction_lat))
            junc_pos_b = info_b["line"].project(Point(junction_lon, junction_lat))

            neighbors_a = _sites_adjacent_to_junction(info_a["snapped"], junc_pos_a)
            neighbors_b = _sites_adjacent_to_junction(info_b["snapped"], junc_pos_b)

            for id_a in neighbors_a:
                for id_b in neighbors_b:
                    if id_a != id_b:
                        adjacency[id_a].add(id_b)
                        adjacency[id_b].add(id_a)


def _sites_adjacent_to_junction(
    snapped: list[tuple[float, str]],
    junction_pos: float,
) -> list[str]:
    """Return the sites immediately before and after junction_pos on a trail."""
    before: str | None = None
    after: str | None = None
    for pos, div_id in snapped:
        if pos <= junction_pos:
            before = div_id
        elif after is None:
            after = div_id
            break
    return [d for d in (before, after) if d is not None]
