"""
Live API calls to Recreation.gov and OpenStreetMap Overpass.

Recreation.gov endpoints (no API key required):
  GET /api/permitcontent/{facility_id}
      Returns all permit sites (divisions) with GPS coordinates and names.

  GET /api/permititinerary/{facility_id}/division/{div_id}/availability/month
      Returns per-night permit quota: how many spots remain on each date.

OpenStreetMap Overpass API (no API key required):
  Returns all named hiking trail ways within a bounding box as ordered
  GPS polylines. OSM is the underlying trail data source for AllTrails,
  Gaia GPS, and Caltopo.

Used only when --live is passed. The mock module mirrors these return shapes
so the rest of the system works identically in both modes.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date

import requests

_REC_GOV_BASE = "https://www.recreation.gov/api"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Mimic a browser so rec.gov does not reject the request.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.recreation.gov/",
}

# Seconds to wait between rec.gov calls to avoid rate limiting.
_RATE_LIMIT_SECONDS = 1.0


def fetch_sites(facility_id: str) -> list[dict]:
    """
    Fetch all active, non-group permit sites for a park.

    Returns a list of dicts, each with:
      division_id (str), name (str), lat (float), lon (float), district (str)

    Source: GET /api/permitcontent/{facility_id}
    """
    url = f"{_REC_GOV_BASE}/permitcontent/{facility_id}"
    response = requests.get(url, headers=_HEADERS, timeout=30)
    response.raise_for_status()

    divisions = response.json()["payload"]["divisions"]

    sites = []
    for div_id, div in divisions.items():
        if not div.get("is_active", True):
            continue
        if _is_group_site(div.get("name", "")):
            continue
        if _is_placeholder_site(div.get("name", "")):
            continue
        lat = div.get("latitude", 0)
        lon = div.get("longitude", 0)
        if lat == 0 or lon == 0:
            continue
        sites.append({
            "division_id": div_id,
            "name": div["name"],
            "lat": float(lat),
            "lon": float(lon),
            "district": div.get("district", ""),
        })

    return sites


def fetch_availability(
    facility_id: str,
    division_id: str,
    start_date: date,
) -> dict[str, int]:
    """
    Fetch per-night permit availability for one site.

    Returns a dict mapping date strings (YYYY-MM-DD) to remaining permit count.
    A count of 0 means fully booked. Missing dates have unknown availability.

    Source: GET /api/permititinerary/{facility_id}/division/{div_id}/availability/month
    """
    url = (
        f"{_REC_GOV_BASE}/permititinerary/{facility_id}"
        f"/division/{division_id}/availability/month"
    )
    params = {"start_date": start_date.strftime("%Y-%m-%dT00:00:00.000Z")}

    time.sleep(_RATE_LIMIT_SECONDS)
    response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
    response.raise_for_status()

    quota_maps = response.json()["payload"]["quota_type_maps"]
    daily = quota_maps.get("ConstantQuotaUsageDaily", {})

    return {date_str: entry["remaining"] for date_str, entry in daily.items()}


def fetch_trails(bbox: tuple[float, float, float, float]) -> list[dict]:
    """
    Fetch all named hiking trail ways from OpenStreetMap within a bounding box.

    bbox = (south_lat, west_lon, north_lat, east_lon)

    Returns a list of trail dicts, each with:
      osm_id (str)     - unique OSM way ID
      name (str)       - trail name from OSM tags
      node_ids (list)  - ordered OSM node IDs along the trail
      points (list)    - ordered (lat, lon) tuples matching node_ids

    Trails that span multiple OSM way segments sharing the same name are
    stitched into a single ordered polyline before returning.

    Source: OpenStreetMap Overpass API
    """
    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"

    query = f"""
[out:json][timeout:60];
way["highway"~"^(path|footway)$"]["name"]({bbox_str});
out body geom;
"""
    response = requests.post(_OVERPASS_URL, data={"data": query}, timeout=90)
    response.raise_for_status()

    raw_ways = []
    for element in response.json().get("elements", []):
        if element["type"] != "way":
            continue
        name = element.get("tags", {}).get("name", "").strip()
        geometry = element.get("geometry", [])
        if not name or len(geometry) < 2:
            continue
        raw_ways.append({
            "osm_id": str(element["id"]),
            "name": name,
            "node_ids": element["nodes"],
            "points": [(pt["lat"], pt["lon"]) for pt in geometry],
        })

    return _stitch_ways_by_name(raw_ways)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_group_site(name: str) -> bool:
    """Group sites are shared campsites excluded from permit chain searches."""
    return "Group" in name or "group" in name


def _is_placeholder_site(name: str) -> bool:
    """
    Placeholder divisions in the rec.gov system represent nights spent
    outside the wilderness (e.g., at frontcountry campgrounds). They are
    not real backcountry sites and should not appear as graph nodes.
    """
    return "Other Accommodations" in name or "Placeholder" in name


def _stitch_ways_by_name(raw_ways: list[dict]) -> list[dict]:
    """
    Join OSM way segments that share the same trail name into single polylines.

    OSM often splits a single named trail into multiple way elements where
    the trail changes attributes (surface, access, etc.). Two segments with
    the same name that share an endpoint node are joined in traversal order.

    Segments that cannot be connected to a named trail (isolated fragments)
    are returned individually.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    for way in raw_ways:
        by_name[way["name"]].append(way)

    stitched = []
    for name, segments in by_name.items():
        stitched.extend(_stitch_segments(name, segments))
    return stitched


def _stitch_segments(name: str, segments: list[dict]) -> list[dict]:
    """
    Stitch a list of same-named trail segments into one or more polylines.

    Returns multiple polylines if the segments form disconnected sub-trails
    (e.g., two separate trails with the same name in different valleys).
    """
    if len(segments) == 1:
        return segments

    # Map endpoint node_id → list of segment indices that end there.
    endpoint_map: dict[int, list[int]] = defaultdict(list)
    for i, seg in enumerate(segments):
        endpoint_map[seg["node_ids"][0]].append(i)
        endpoint_map[seg["node_ids"][-1]].append(i)

    visited = set()
    result = []

    for start_idx in range(len(segments)):
        if start_idx in visited:
            continue

        # Walk the chain of segments from this starting segment.
        chain_node_ids: list[int] = []
        chain_points: list[tuple] = []
        visited.add(start_idx)

        seg = segments[start_idx]
        # Orient so we start from the true trail endpoint (node shared by only one segment).
        first_node = seg["node_ids"][0]
        last_node = seg["node_ids"][-1]
        start_from_beginning = len(endpoint_map[first_node]) == 1

        node_ids = seg["node_ids"] if start_from_beginning else list(reversed(seg["node_ids"]))
        points = seg["points"] if start_from_beginning else list(reversed(seg["points"]))
        chain_node_ids.extend(node_ids)
        chain_points.extend(points)

        # Follow connecting segments until no more can be appended.
        while True:
            tail_node = chain_node_ids[-1]
            next_indices = [i for i in endpoint_map[tail_node] if i not in visited]
            if not next_indices:
                break

            next_idx = next_indices[0]
            visited.add(next_idx)
            next_seg = segments[next_idx]

            # Append next segment in the direction that continues from tail_node.
            if next_seg["node_ids"][0] == tail_node:
                chain_node_ids.extend(next_seg["node_ids"][1:])
                chain_points.extend(next_seg["points"][1:])
            else:
                chain_node_ids.extend(list(reversed(next_seg["node_ids"]))[1:])
                chain_points.extend(list(reversed(next_seg["points"]))[1:])

        result.append({
            "osm_id": segments[start_idx]["osm_id"],
            "name": name,
            "node_ids": chain_node_ids,
            "points": chain_points,
        })

    return result
