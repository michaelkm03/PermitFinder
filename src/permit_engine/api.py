"""
Live API calls to Recreation.gov and OpenStreetMap Overpass.

Recreation.gov endpoints (no API key required):
  GET /api/permitcontent/{facility_id}
      Returns all permit sites (divisions) with GPS coordinates and names.

  ITINERARY parks (Rainier):
    GET /api/permititinerary/{facility_id}/division/{div_id}/availability/month
        Returns per-night permit quota via quota_type_maps.ConstantQuotaUsageDaily.

  QUOTA parks (NC, Olympic):
    GET /api/permits/{facility_id}/divisions/{div_id}/availability
        Returns per-night remaining counts. Shape A: {remaining:int},
        Shape B: "Available" string. Availability API is pre-season until
        the reservation open date; 4xx responses are treated as no data.

OpenStreetMap Overpass API (no API key required):
  Returns all named hiking trail ways within a bounding box as ordered
  GPS polylines. OSM is the underlying trail data source for AllTrails,
  Gaia GPS, and Caltopo.

Used only when --live is passed. The mock module mirrors these return shapes
so the rest of the system works identically in both modes.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date

import requests

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REC_GOV_BASE = "https://www.recreation.gov/api"
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

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
_RATE_LIMIT_SECONDS = 0.5

# In-process cache: (facility_id, division_id, month, year) -> availability dict.
# Avoids repeat calls if the same site is queried more than once in a session.
_availability_cache: dict[tuple, dict[str, int]] = {}

# NOTE: No bulk availability endpoint exists for ITINERARY parks.
# Confirmed via HAR capture of rec.gov's own frontend — the browser makes one
# GET /api/permititinerary/{facility_id}/division/{div_id}/availability/month
# call per division. There is no facility-level endpoint that returns all
# divisions at once. The Enchantments (ZONE) endpoint is the only bulk option
# and is specific to that permit system.


def fetch_sites(facility_id: str) -> list[dict]:
    """
    Fetch all active, non-group permit sites for a park.

    Returns a list of dicts, each with:
      division_id (str), name (str), lat (float), lon (float), district (str)

    Source: GET /api/permitcontent/{facility_id}
    """
    url = f"{_REC_GOV_BASE}/permitcontent/{facility_id}"
    log.debug("fetch_sites  facility=%s  GET %s", facility_id, url)
    t0 = time.perf_counter()
    response = requests.get(url, headers=_HEADERS, timeout=30)
    log.debug("fetch_sites  status=%d  size=%s bytes  elapsed=%.3fs",
              response.status_code,
              response.headers.get("content-length", len(response.content)),
              time.perf_counter() - t0)
    response.raise_for_status()

    divisions = response.json()["payload"]["divisions"]

    sites = []
    for div_id, div in divisions.items():
        skip_reason = None
        if not div.get("is_active", True):
            skip_reason = "inactive"
        elif _is_placeholder_site(div.get("name", "")):
            skip_reason = "placeholder"
        elif _is_zone_parent(div.get("name", ""), div.get("district", "")):
            skip_reason = "zone-parent"
        elif div.get("is_accessible_as_child_only", False):
            skip_reason = "child-only"
        elif div.get("latitude", 0) == 0 or div.get("longitude", 0) == 0:
            skip_reason = "no-coords"

        lat = div.get("latitude", 0)
        lon = div.get("longitude", 0)
        div_type = (div.get("type") or div.get("division_type") or "").strip()
        district = div.get("district", "")

        log.debug("  div %-20s  %-40s  district=%-25s  %s",
                  div_id, repr(div.get("name", "")), repr(district),
                  f"SKIP({skip_reason})" if skip_reason else "OK")

        if skip_reason:
            continue

        sites.append({
            "division_id": div_id,
            "name": div["name"],
            "lat": float(lat),
            "lon": float(lon),
            "district": district,
            "type": div_type,
        })

    log.debug("fetch_sites  %d raw divisions → %d sites after filters", len(divisions), len(sites))
    return sites


def fetch_availability(
    facility_id: str,
    division_id: str,
    start_date: date,
    permit_type: str = "ITINERARY",
) -> dict[str, int]:
    """
    Fetch per-night permit availability for one division/site.

    Returns a dict mapping date strings (YYYY-MM-DD) to remaining permit count:
      > 0  — permits available for online booking
        0  — fully booked (no permits of any kind)
       -2  — walk-up / in-station only: online quota is 0 but ranger-station
              quota (QuotaUsageByMemberDaily) is still > 0. The site appears as
              "In Station" on recreation.gov — permits must be obtained in person.
    An empty dict means data is unavailable (pre-season, API error, or no quota
    data present in the response).

    The distinction between 0 and -2 comes from two quota types in the API
    response (confirmed via HAR capture):
      ConstantQuotaUsageDaily  — online reservation quota (what you book online)
      QuotaUsageByMemberDaily  — total quota including ranger-station walk-ups

    When ConstantQuotaUsageDaily.remaining = 0 but QuotaUsageByMemberDaily.remaining > 0,
    the date is walk-up only. Both at 0 means the date is truly fully booked.

    Endpoints confirmed via HAR capture on the detailed-availability page:
      "ITINERARY" — /api/permititinerary/{facility_id}/division/{div_id}/availability/month
                    Params: month=M&year=YYYY
                    Response: payload.quota_type_maps.ConstantQuotaUsageDaily (reservation counts)
                    Used by: Rainier (4675317), Olympic (4098362), NC (4675322, assumed)

      "ZONE"      — /api/permitinyo/{facility_id}/availabilityv2
                    Params: start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&commercial_acct=false
                    Response: payload[date][zone_id].constant_quota_usage_daily.remaining
                    Used by: Enchantments (445863)
                    NOTE: division_id is ignored for ZONE — one call returns all zones.
    """
    if permit_type == "ZONE":
        return _fetch_availability_zone(facility_id, division_id, start_date)

    # ITINERARY (and legacy QUOTA label): permititinerary endpoint, confirmed via HAR.
    cache_key = (facility_id, division_id, start_date.month, start_date.year)
    if cache_key in _availability_cache:
        log.debug("fetch_availability  cache hit  division=%s  %d/%d",
                  division_id, start_date.month, start_date.year)
        return _availability_cache[cache_key]

    url = (
        f"{_REC_GOV_BASE}/permititinerary/{facility_id}"
        f"/division/{division_id}/availability/month"
    )
    params = {"month": start_date.month, "year": start_date.year}

    time.sleep(_RATE_LIMIT_SECONDS)

    log.debug("fetch_availability  division=%s  type=%s  %d/%d  GET %s",
              division_id, permit_type, start_date.month, start_date.year, url)
    t0 = time.perf_counter()

    try:
        response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
        elapsed = time.perf_counter() - t0
        log.debug("fetch_availability  status=%d  size=%s bytes  elapsed=%.3fs",
                  response.status_code,
                  response.headers.get("content-length", len(response.content)),
                  elapsed)

        if response.status_code >= 400:
            log.debug("fetch_availability  HTTP %d — pre-season or wrong endpoint, returning {}",
                      response.status_code)
            return {}
        response.raise_for_status()

    except requests.exceptions.RequestException as exc:
        log.debug("fetch_availability  request error: %s", exc)
        return {}

    try:
        body = response.json()
    except Exception as exc:
        log.debug("fetch_availability  JSON parse error: %s", exc)
        return {}

    payload = body.get("payload", {})

    # ConstantQuotaUsageDaily[date].remaining — advance reservation slots left.
    # remaining > 0 → bookable now on recreation.gov.
    # remaining = 0 → fully reserved for that date.
    # Empty dict   → pre-season, no reservation data exists yet.
    quota_maps   = payload.get("quota_type_maps", {}) if isinstance(payload, dict) else {}
    daily        = quota_maps.get("ConstantQuotaUsageDaily", {})
    member_daily = quota_maps.get("QuotaUsageByMemberDaily", {})

    if daily:
        result: dict[str, int] = {}
        for date_str, entry in daily.items():
            const_rem = entry["remaining"]
            if const_rem == 0:
                # Online quota exhausted. Check whether walk-up (ranger-station)
                # quota remains. QuotaUsageByMemberDaily tracks all permit types
                # including those issued at the station rather than online.
                member_entry = member_daily.get(date_str, {})
                member_rem   = member_entry.get("remaining", 0) if member_entry else 0
                result[date_str] = -2 if member_rem > 0 else 0
            else:
                result[date_str] = const_rem

        available = sum(1 for v in result.values() if v > 0)
        walkup    = sum(1 for v in result.values() if v == -2)
        log.debug("fetch_availability  %d dates: %d available online, %d walk-up, %d booked",
                  len(result), available, walkup, len(result) - available - walkup)
        _availability_cache[cache_key] = result
        return result

    log.debug("fetch_availability  ConstantQuotaUsageDaily empty — pre-season, returning {}")
    return {}


def _fetch_availability_zone(
    facility_id: str,
    division_id: str,
    start_date: date,
) -> dict[str, int]:
    """
    Fetch availability for one zone via the permitinyo endpoint (Enchantments).

    One API call returns all zones for all dates in the month; we filter to division_id.

    Source: GET /api/permitinyo/{facility_id}/availabilityv2
              ?start_date=YYYY-MM-01&end_date=YYYY-MM-01(next month)&commercial_acct=false
    Response: payload[date_str][zone_id].constant_quota_usage_daily.{total, remaining}

    Confirmed via HAR: 445863_detailed-availability.har
    """
    year, month = start_date.year, start_date.month
    start_of_month = date(year, month, 1)
    if month == 12:
        end_of_month = date(year + 1, 1, 1)
    else:
        end_of_month = date(year, month + 1, 1)

    url = f"{_REC_GOV_BASE}/permitinyo/{facility_id}/availabilityv2"
    params = {
        "start_date": start_of_month.strftime("%Y-%m-%d"),
        "end_date": end_of_month.strftime("%Y-%m-%d"),
        "commercial_acct": "false",
    }

    time.sleep(_RATE_LIMIT_SECONDS)

    log.debug("fetch_availability (ZONE)  facility=%s  division=%s  %d/%d  GET %s",
              facility_id, division_id, month, year, url)
    t0 = time.perf_counter()

    try:
        response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
        elapsed = time.perf_counter() - t0
        log.debug("fetch_availability (ZONE)  status=%d  size=%s bytes  elapsed=%.3fs",
                  response.status_code,
                  response.headers.get("content-length", len(response.content)),
                  elapsed)
        if response.status_code >= 400:
            log.debug("fetch_availability (ZONE)  HTTP %d — pre-season or wrong endpoint, returning {}",
                      response.status_code)
            return {}
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        log.debug("fetch_availability (ZONE)  request error: %s", exc)
        return {}

    try:
        body = response.json()
    except Exception as exc:
        log.debug("fetch_availability (ZONE)  JSON parse error: %s", exc)
        return {}

    payload = body.get("payload", {})
    log.debug("fetch_availability (ZONE)  payload contains %d dates", len(payload))

    result: dict[str, int] = {}
    for date_str, zones in payload.items():
        if not isinstance(zones, dict):
            continue
        zone = zones.get(division_id)
        if zone is None:
            continue
        remaining = zone.get("constant_quota_usage_daily", {}).get("remaining", 0)
        result[date_str] = remaining

    available = sum(1 for v in result.values() if v > 0)
    log.debug("fetch_availability (ZONE)  division=%s  %d dates, %d with remaining > 0",
              division_id, len(result), available)
    return result


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

    query = f"""[out:json][timeout:60];
way["highway"~"^(path|footway)$"]["name"]({bbox_str});
out body geom;
"""
    last_exc: Exception = RuntimeError("No Overpass mirrors available")
    osm_data: dict = {}
    for mirror in _OVERPASS_MIRRORS:
        try:
            log.debug("fetch_trails  POST %s", mirror)
            t0 = time.perf_counter()
            response = requests.post(mirror, data={"data": query}, timeout=90)
            log.debug("fetch_trails  status=%d  elapsed=%.3fs", response.status_code, time.perf_counter() - t0)
            response.raise_for_status()
            osm_data = response.json()  # raises JSONDecodeError on empty/bad body
            break
        except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError) as exc:
            log.debug("fetch_trails  mirror error: %s — trying next", exc)
            last_exc = exc
            continue
    else:
        raise last_exc

    raw_ways = []
    for element in osm_data.get("elements", []):
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

    stitched = _stitch_ways_by_name(raw_ways)
    log.debug("fetch_trails  %d raw OSM ways → %d stitched trails", len(raw_ways), len(stitched))
    return stitched


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


def _is_zone_parent(name: str, district: str) -> bool:
    """
    Zone/area parent nodes have the same name as their district.

    rec.gov uses a parent division (name == district) as a container grouping
    real campsites. This parent is not a bookable overnight stop and does not
    appear on the website's availability grid — only its children do.
    """
    return bool(name and district and name.strip() == district.strip())


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
