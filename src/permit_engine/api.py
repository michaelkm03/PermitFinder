"""
Live API calls to Recreation.gov and OpenStreetMap Overpass.

Recreation.gov endpoints (no API key required):
  GET /api/permitcontent/{facility_id}
      All permit sites (divisions) for a park — names, GPS coords, district.
      Cached 30 days in ~/.cache/permit-finder/cache.db.

  GET /api/permititinerary/{facility_id}/division/{div_id}/availability/month
      Per-night permit quota for one site, for one month.
      Response: payload.quota_type_maps.ConstantQuotaUsageDaily[date].{total, remaining}
      Used by all supported parks (Rainier, Olympic, North Cascades).
      No bulk endpoint exists — one call per site, confirmed via HAR.

  GET /api/permitinyo/{facility_id}/availabilityv2
      Zone-based availability for Enchantments. One call returns all zones.

OpenStreetMap Overpass API (no API key required):
  Named hiking trail ways within a bounding box, as ordered GPS polylines.
  Tried across multiple public mirrors; first successful non-empty response used.
  Cached 30 days in ~/.cache/permit-finder/cache.db.

Used only when --live is passed. mock.py mirrors these return shapes so the
graph builder and search engine work identically in both modes.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date

import requests

from permit_engine.cache import get_default_cache, make_key

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REC_GOV_BASE = "https://www.recreation.gov/api"

# Overpass mirrors tried in order; first to return a non-empty result is used.
# osm.ch is excluded — returns 200 with 0 ways for North American bboxes.
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
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

_RATE_LIMIT_SECONDS = 0.5  # seconds between rec.gov calls to avoid rate limiting

# Disk cache TTLs (days). Trail geometry and site lists are stable;
# availability is never cached (changes daily).
_TTL_TRAILS = 30
_TTL_SITES  = 30

# In-process availability cache for the current session.
# Key: (facility_id, division_id, month, year). Prevents duplicate calls when
# the same site appears in multiple chains being evaluated.
_availability_cache: dict[tuple, dict[str, int]] = {}


def fetch_sites(facility_id: str) -> list[dict]:
    """
    Fetch all active, non-group permit sites for a park.

    Returns a list of dicts, each with:
      division_id (str)    — rec.gov division ID
      name        (str)    — campsite name
      lat         (float)  — GPS latitude
      lon         (float)  — GPS longitude
      district    (str)    — trail district / area name
      type        (str)    — division type (e.g. "Campsite")
      children    (list)   — adjacent division IDs along the trail (from rec.gov)

    The children field encodes trail adjacency directly from rec.gov — no GPS
    snapping or external map data is needed to build the trail graph.

    Source: GET /api/permitcontent/{facility_id}
    Results are cached for 30 days (trail topology rarely changes).
    """
    cache = get_default_cache()
    cache_key = make_key("sites", facility_id)
    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("fetch_sites  facility=%s  cache hit (%d sites)", facility_id, len(cached))
        return cached

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

        # children: list of adjacent division IDs along the trail.
        # rec.gov stores these as strings in the API response.
        raw_children = div.get("children") or []
        children = [str(c) for c in raw_children if c]

        sites.append({
            "division_id": div_id,
            "name": div["name"],
            "lat": float(lat),
            "lon": float(lon),
            "district": district,
            "type": div_type,
            "children": children,
        })

    log.debug("fetch_sites  %d raw divisions → %d sites after filters", len(divisions), len(sites))
    cache.set(cache_key, sites, ttl_days=_TTL_SITES)
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
    # remaining = 0 AND total > 0 → fully reserved for that date.
    # remaining = 0 AND total = 0 → no per-site quota; fall back to bools field.
    # Empty dict   → pre-season, no reservation data exists yet.
    #
    # When total = 0, the site has no individual daily quota (ITINERARY parks like
    # Olympic book against the overall itinerary, not per-site). In this case
    # bools[date] is the authoritative availability signal (true = bookable).
    quota_maps   = payload.get("quota_type_maps", {}) if isinstance(payload, dict) else {}
    daily        = quota_maps.get("ConstantQuotaUsageDaily", {})
    member_daily = quota_maps.get("QuotaUsageByMemberDaily", {})
    bools        = payload.get("bools", {}) if isinstance(payload, dict) else {}

    if daily:
        result: dict[str, int] = {}
        for date_str, entry in daily.items():
            const_rem   = entry["remaining"]
            const_total = entry.get("total", -1)
            if const_rem == 0 and const_total == 0:
                # No per-site quota configured — use bools as ground truth.
                result[date_str] = 1 if bools.get(date_str, False) else 0
            elif const_rem == 0:
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
      osm_id   (str)  — unique OSM way ID
      name     (str)  — trail name from OSM tags
      node_ids (list) — ordered OSM node IDs along the trail
      points   (list) — ordered (lat, lon) tuples matching node_ids

    Segments of the same named trail are stitched into a single ordered
    polyline before returning.

    Tries each Overpass mirror in _OVERPASS_MIRRORS until one returns a
    non-empty result. Results are cached for 30 days.
    """
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    cache = get_default_cache()
    cache_key = make_key("trails", bbox_str)
    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("fetch_trails  cache hit  %d trails  bbox=%s", len(cached), bbox_str)
        return cached

    # Server-side timeout of 180 s keeps Overpass from silently dropping slow queries.
    query = (
        f"[out:json][timeout:180][maxsize:536870912];\n"
        f'way["highway"~"^(path|footway)$"]["name"]({bbox_str});\n'
        f"out body geom;\n"
    )

    osm_data: dict = {}
    last_exc: Exception = RuntimeError("No Overpass mirrors available")
    for mirror in _OVERPASS_MIRRORS:
        try:
            log.debug("fetch_trails  POST %s", mirror)
            t0 = time.perf_counter()
            resp = requests.post(mirror, data={"data": query}, timeout=150)
            elapsed = time.perf_counter() - t0
            log.debug("fetch_trails  status=%d  elapsed=%.1fs", resp.status_code, elapsed)
            resp.raise_for_status()
            osm_data = resp.json()
            if osm_data.get("elements"):
                break  # got real data — stop trying mirrors
            log.debug("fetch_trails  mirror returned 0 elements — trying next")
        except (requests.exceptions.RequestException, ValueError) as exc:
            log.debug("fetch_trails  mirror error: %s — trying next", exc)
            last_exc = exc
    else:
        # All mirrors failed or returned empty.
        if not osm_data.get("elements"):
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

    # Only cache non-empty results — empty may indicate a transient failure.
    if stitched:
        cache.set(cache_key, stitched, ttl_days=_TTL_TRAILS)

    return stitched


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_placeholder_site(name: str) -> bool:
    """Frontcountry placeholder divisions — not real backcountry sites."""
    return "Other Accommodations" in name or "Placeholder" in name


def _is_zone_parent(name: str, district: str) -> bool:
    """
    rec.gov container divisions whose name equals their district name.
    These group real campsites but are not bookable overnight stops themselves.
    """
    return bool(name and district and name.strip() == district.strip())


def _stitch_ways_by_name(raw_ways: list[dict]) -> list[dict]:
    """
    Join OSM way segments that share the same trail name into single polylines.

    OSM often splits a single named trail across multiple way elements where
    attributes change (surface, access restrictions, etc.). Segments sharing
    the same name and a common endpoint node are joined in traversal order.
    Isolated fragments (no shared endpoints) are returned individually.
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
    Stitch same-named trail segments into one or more ordered polylines.

    Returns multiple polylines when segments form disconnected sub-trails
    (e.g. two separate trails with the same name in different valleys).
    """
    if len(segments) == 1:
        return segments

    # Map endpoint node_id → list of segment indices that end there.
    endpoint_map: dict[int, list[int]] = defaultdict(list)
    for i, seg in enumerate(segments):
        endpoint_map[seg["node_ids"][0]].append(i)
        endpoint_map[seg["node_ids"][-1]].append(i)

    visited: set[int] = set()
    result = []

    for start_idx in range(len(segments)):
        if start_idx in visited:
            continue

        chain_node_ids: list[int] = []
        chain_points: list[tuple] = []
        visited.add(start_idx)

        seg = segments[start_idx]
        # Orient so we start from the true trail endpoint (node in only one segment).
        start_from_beginning = len(endpoint_map[seg["node_ids"][0]]) == 1
        node_ids = seg["node_ids"] if start_from_beginning else list(reversed(seg["node_ids"]))
        points   = seg["points"]   if start_from_beginning else list(reversed(seg["points"]))
        chain_node_ids.extend(node_ids)
        chain_points.extend(points)

        while True:
            tail_node = chain_node_ids[-1]
            next_indices = [i for i in endpoint_map[tail_node] if i not in visited]
            if not next_indices:
                break

            next_idx = next_indices[0]
            visited.add(next_idx)
            next_seg = segments[next_idx]
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
