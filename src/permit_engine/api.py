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

import sys
import time
from collections import defaultdict
from datetime import date

import requests

# ---------------------------------------------------------------------------
# Verbose logging
# ---------------------------------------------------------------------------

_verbose = False


def set_verbose(flag: bool) -> None:
    global _verbose
    _verbose = flag


def _vlog(*args: object) -> None:
    if _verbose:
        print("[verbose]", *args, file=sys.stderr)


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
_RATE_LIMIT_SECONDS = 1.0


def fetch_sites(facility_id: str) -> list[dict]:
    """
    Fetch all active, non-group permit sites for a park.

    Returns a list of dicts, each with:
      division_id (str), name (str), lat (float), lon (float), district (str)

    Source: GET /api/permitcontent/{facility_id}
    """
    url = f"{_REC_GOV_BASE}/permitcontent/{facility_id}"
    _vlog(f"")
    _vlog(f"── fetch_sites ─────────────────────────────────────────────────")
    _vlog(f"  facility_id  : {facility_id}")
    _vlog(f"  GET {url}")
    response = requests.get(url, headers=_HEADERS, timeout=30)
    _vlog(f"  status       : {response.status_code}")
    _vlog(f"  content-len  : {response.headers.get('content-length', len(response.content))} bytes")
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

    _vlog(f"  raw divisions: {len(divisions)}, after filters: {len(sites)}")
    for s in sites:
        _vlog(f"    div {s['division_id']:>15}  {s['name']!r:40}  lat={s['lat']:.4f}  lon={s['lon']:.4f}")
    return sites


def fetch_availability(
    facility_id: str,
    division_id: str,
    start_date: date,
    permit_type: str = "ITINERARY",
) -> dict[str, int]:
    """
    Fetch per-night permit availability for one division/site.

    Returns a dict mapping date strings (YYYY-MM-DD) to remaining permit count.
    A count of 0 means fully booked. An empty dict means data is unavailable
    (pre-season, API error, or no quota data present in response).

    Endpoints confirmed via HAR capture on the detailed-availability page:
      "ITINERARY" — /api/permititinerary/{facility_id}/division/{div_id}/availability/month
                    Params: month=M&year=YYYY
                    Response: payload.quota_type_maps.ConstantQuotaUsageDaily (reservation counts)
                              payload.bools (walk-up signal, used as fallback)
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
    url = (
        f"{_REC_GOV_BASE}/permititinerary/{facility_id}"
        f"/division/{division_id}/availability/month"
    )
    params = {"month": start_date.month, "year": start_date.year}

    time.sleep(_RATE_LIMIT_SECONDS)

    _vlog(f"")
    _vlog(f"── fetch_availability ──────────────────────────────────────────")
    _vlog(f"  facility_id  : {facility_id}")
    _vlog(f"  division_id  : {division_id}")
    _vlog(f"  permit_type  : {permit_type}")
    _vlog(f"  month/year   : {start_date.month}/{start_date.year}")
    _vlog(f"  GET {url}")
    _vlog(f"  params       : {params}")

    try:
        response = requests.get(url, headers=_HEADERS, params=params, timeout=30)

        _vlog(f"  status       : {response.status_code}")
        _vlog(f"  content-type : {response.headers.get('content-type', 'n/a')}")
        _vlog(f"  content-len  : {response.headers.get('content-length', len(response.content))} bytes")

        if response.status_code >= 400:
            _vlog(f"  body (400+)  : {response.text[:400]}")
            _vlog(f"  → HTTP {response.status_code} — pre-season or wrong endpoint, returning {{}}")
            return {}
        response.raise_for_status()

    except requests.exceptions.RequestException as exc:
        _vlog(f"  request error: {exc}")
        return {}

    try:
        body = response.json()
    except Exception as exc:
        _vlog(f"  JSON parse error: {exc}")
        _vlog(f"  raw body[:200]: {response.text[:200]}")
        return {}

    payload = body.get("payload", {})
    _vlog(f"  payload keys : {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")

    # ── Primary: ConstantQuotaUsageDaily (reservation remaining counts) ──────
    quota_maps = payload.get("quota_type_maps", {}) if isinstance(payload, dict) else {}
    daily = quota_maps.get("ConstantQuotaUsageDaily", {})
    _vlog(f"  quota_type_maps keys: {list(quota_maps.keys())}")
    _vlog(f"  ConstantQuotaUsageDaily dates: {len(daily)}")
    if daily:
        sample = dict(list(daily.items())[:3])
        _vlog(f"  sample (first 3): {sample}")

    if daily:
        result = {date_str: entry["remaining"] for date_str, entry in daily.items()}
        available = sum(1 for v in result.values() if v > 0)
        _vlog(f"  → parsed from quota_maps: {len(result)} dates, {available} with remaining > 0")
        return result

    # ── Fallback: bools field (walk-up / open signal) ────────────────────────
    bools = payload.get("bools", {}) if isinstance(payload, dict) else {}
    _vlog(f"  bools dates  : {len(bools)}")
    if bools:
        sample_bools = dict(list(bools.items())[:3])
        _vlog(f"  bools sample (first 3): {sample_bools}")
        any_true = any(bools.values())
        if any_true:
            result = {date_str: (1 if val else 0) for date_str, val in bools.items()}
            available = sum(1 for v in result.values() if v > 0)
            _vlog(f"  → parsed from bools: {len(result)} dates, {available} available")
            return result

    _vlog(f"  → no quota_maps and no true bools — returning {{}} (pre-season / no data)")
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

    _vlog(f"")
    _vlog(f"── fetch_availability (ZONE) ────────────────────────────────────")
    _vlog(f"  facility_id  : {facility_id}")
    _vlog(f"  division_id  : {division_id}")
    _vlog(f"  month/year   : {month}/{year}")
    _vlog(f"  GET {url}")
    _vlog(f"  params       : {params}")

    try:
        response = requests.get(url, headers=_HEADERS, params=params, timeout=30)
        _vlog(f"  status       : {response.status_code}")
        _vlog(f"  content-type : {response.headers.get('content-type', 'n/a')}")
        _vlog(f"  content-len  : {response.headers.get('content-length', len(response.content))} bytes")
        if response.status_code >= 400:
            _vlog(f"  body (400+)  : {response.text[:400]}")
            _vlog(f"  → HTTP {response.status_code} — pre-season or wrong endpoint, returning {{}}")
            return {}
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        _vlog(f"  request error: {exc}")
        return {}

    try:
        body = response.json()
    except Exception as exc:
        _vlog(f"  JSON parse error: {exc}")
        return {}

    payload = body.get("payload", {})
    _vlog(f"  payload dates: {len(payload)}")

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
    _vlog(f"  division {division_id}: {len(result)} dates, {available} with remaining > 0")
    if result:
        sample = dict(list(result.items())[:3])
        _vlog(f"  sample (first 3): {sample}")
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
            _vlog(f"POST {mirror}  query={query.strip()[:80]!r}...")
            response = requests.post(mirror, data={"data": query}, timeout=90)
            _vlog(f"  → {response.status_code}")
            response.raise_for_status()
            osm_data = response.json()  # raises JSONDecodeError on empty/bad body
            break
        except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError) as exc:
            _vlog(f"  error: {exc} — trying next mirror")
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

    _vlog(f"  raw OSM ways: {len(raw_ways)}")
    stitched = _stitch_ways_by_name(raw_ways)
    _vlog(f"  stitched trails: {len(stitched)}")
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
