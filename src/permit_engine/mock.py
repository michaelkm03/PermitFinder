"""
Mock data matching the exact return shapes of api.fetch_sites(),
api.fetch_trails(), and api.fetch_availability().

Used when --live is NOT passed. Drop-in replacement for the api module —
the graph builder and search engine receive identical data structures
regardless of which source is active.

Site data is based on real North Cascades East Bank Trail division IDs and
coordinates sourced from the rec.gov /api/permitcontent/4675322 response
(verified March 2026 HAR export). Availability is synthetic but covers
realistic booking scenarios including all three availability states:

  > 0  permits remaining for online booking
    0  fully booked (no permits anywhere)
   -2  walk-up / in-station only (online quota = 0, ranger-station quota > 0)
   -1  no data / pre-season (not represented here — mock always returns data)

Mock trail topology
-------------------
Three trails exercise all adjacency scenarios used by build_graph():

  East Bank Trail (linear, 4 camps):
      South TH (node 9001) ── CampA ── CampB ── CampC ── CampD ── North TH (9015)

  Nightmare Loop Trail (genuine mid-trail junction at node 9008):
      node 9008 is mid-trail on East Bank AND the start endpoint of Nightmare Loop.
      CampC ↔ CampE edge is always valid (genuine junction, not trailhead).

  Copper Ridge Trail (shared parking-lot trailhead at node 9001):
      node 9001 is endpoint of BOTH East Bank and Copper Ridge.
      CampA ↔ CampF edge is a TRAILHEAD connection:
        blocked when allow_trailhead=False, allowed when allow_trailhead=True.

Mock availability scenarios (2026-07-15 window)
------------------------------------------------
  Jul 15–17  all-open window: all sites have remaining >= 1
  Jul 16     Roland Creek = 0 — breaks any 2-night chain through it on night 2
  Jul 18     Devils Creek = 0 — blocks 4-night chains ending there
  Jul 15–18  Nightmare Camp = -2 — walk-up / in-station only; shows as "stn"
  Jul 20     all sites = 0 — fully booked, no chains possible
"""
from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Sites — real NC East Bank Trail division IDs and coordinates
# ---------------------------------------------------------------------------

# Real division IDs and GPS coordinates from /api/permitcontent/4675322
# (North Cascades, East Bank Trail district).
# children encodes trail adjacency exactly as rec.gov returns it.
_SITES = [
    {
        "division_id": "4675322083",
        "name": "Ruby Pasture Camp",
        "lat": 48.72839,
        "lon": -121.01404,
        "district": "East Bank Trail",
        "type": "Campsite",
        # CampA → CampB only (southernmost camp)
        "children": ["4675322082"],
    },
    {
        "division_id": "4675322082",
        "name": "Roland Creek Camp",
        "lat": 48.77136,
        "lon": -121.02096,
        "district": "East Bank Trail",
        "type": "Campsite",
        # CampB → CampA, CampC
        "children": ["4675322083", "4675322079"],
    },
    {
        "division_id": "4675322079",
        "name": "May Creek Camp",
        "lat": 48.78686,
        "lon": -121.02873,
        "district": "East Bank Trail",
        "type": "Campsite",
        # CampC → CampB, CampD, CampE (junction to Nightmare Loop)
        "children": ["4675322082", "4675322072", "4675322_NIGHTMARE"],
    },
    {
        "division_id": "4675322072",
        "name": "Devils Creek Camp",
        "lat": 48.83771,
        "lon": -121.02015,
        "district": "East Bank Trail",
        "type": "Campsite",
        # CampD → CampC, CampE (also connects to Nightmare Loop)
        "children": ["4675322079", "4675322_NIGHTMARE"],
    },
    # CampE — Nightmare Loop spur (accessible from both CampC and CampD)
    {
        "division_id": "4675322_NIGHTMARE",
        "name": "Nightmare Camp",
        "lat": 48.93380,
        "lon": -120.98643,
        "district": "East Bank Trail",
        "type": "Campsite",
        # CampE → CampC, CampD
        "children": ["4675322079", "4675322072"],
    },
    # CampF — isolated site (no children; exercises the isolated-node code path)
    {
        "division_id": "4675322_COPPER",
        "name": "Copper Ridge Camp",
        "lat": 48.71000,
        "lon": -121.04800,
        "district": "Copper-Chilliwack",
        "type": "Campsite",
        "children": [],
    },
]

# ---------------------------------------------------------------------------
# Trails — synthetic OSM-shaped data covering all three adjacency scenarios
# ---------------------------------------------------------------------------

# East Bank Trail — linear, runs south to north.
# node 9001 = south trailhead (parking lot), node 9015 = north trailhead.
# Sites snap onto this trail at nodes nearest their real coordinates.
_EAST_BANK_TRAIL = {
    "osm_id": "100001",
    "name": "East Bank Trail",
    "node_ids": [
        9001,   # south trailhead (endpoint) — near CampF (Copper Ridge TH)
        9002,
        9003,   # near CampA (Ruby Pasture, 48.7284, -121.0140)
        9004,
        9005,   # near CampB (Roland Creek, 48.7714, -121.0210)
        9006,
        9007,   # near CampC (May Creek, 48.7869, -121.0287)
        9008,   # JUNCTION with Nightmare Loop — mid-trail node on East Bank
        9009,   # near CampD (Devils Creek, 48.8377, -121.0202)
        9010,
        9015,   # north trailhead (endpoint)
    ],
    "points": [
        (48.7100, -121.0050),  # 9001 south TH
        (48.7200, -121.0100),  # 9002
        (48.7284, -121.0140),  # 9003 — Ruby Pasture snaps here
        (48.7500, -121.0180),  # 9004
        (48.7714, -121.0210),  # 9005 — Roland Creek snaps here
        (48.7800, -121.0250),  # 9006
        (48.7869, -121.0287),  # 9007 — May Creek snaps here
        (48.8200, -121.0220),  # 9008 — junction node (mid-trail on East Bank)
        (48.8377, -121.0202),  # 9009 — Devils Creek snaps here
        (48.9000, -121.0300),  # 9010
        (48.9500, -121.0380),  # 9015 north TH
    ],
}

# Nightmare Loop Trail — spur branching off East Bank at node 9008 (mid-trail).
# node 9008 is the endpoint (index 0) of Nightmare Loop but mid-trail on East Bank.
# Because it is NOT an endpoint of East Bank, this is a genuine junction —
# CampC ↔ CampE is always valid regardless of the --trailhead flag.
_NIGHTMARE_LOOP_TRAIL = {
    "osm_id": "100002",
    "name": "Nightmare Loop Trail",
    "node_ids": [
        9008,   # junction with East Bank (endpoint of Nightmare Loop, mid of East Bank)
        9020,
        9021,   # near CampE (Nightmare Camp, 48.9338, -120.9864)
        9022,   # dead-end trailhead
    ],
    "points": [
        (48.8200, -121.0220),  # 9008 — shared junction
        (48.8700, -121.0000),  # 9020
        (48.9338, -120.9864),  # 9021 — Nightmare Camp snaps here
        (48.9600, -120.9700),  # 9022 dead-end TH
    ],
}

# Copper Ridge Trail — starts at the SAME parking lot as East Bank Trail.
# Both trails share node 9001 as their first/endpoint node.
# This is a trailhead connection: blocked by default, included with --trailhead.
_COPPER_RIDGE_TRAIL = {
    "osm_id": "100003",
    "name": "Copper Ridge Trail",
    "node_ids": [
        9001,   # shared parking-lot endpoint with East Bank Trail
        9030,
        9031,   # near CampF (Copper Ridge Camp, 48.7100, -121.0480)
        9032,   # far trailhead
    ],
    "points": [
        (48.7100, -121.0050),  # 9001 — shared parking lot
        (48.7100, -121.0200),  # 9030
        (48.7100, -121.0480),  # 9031 — Copper Ridge Camp snaps here
        (48.7100, -121.0700),  # 9032 far TH
    ],
}

# ---------------------------------------------------------------------------
# Availability — synthetic data reflecting realistic booking scenarios
# ---------------------------------------------------------------------------

# Per-site availability keyed by date string (YYYY-MM-DD) → remaining count.
# Values:  >0 = available online   0 = fully booked   -2 = walk-up/in-station only
_AVAILABILITY: dict[str, dict[str, int]] = {
    "4675322083": {  # Ruby Pasture Camp — mostly open, closed Jul 20
        "2026-07-15": 3,
        "2026-07-16": 2,
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 3,
        "2026-07-20": 0,
    },
    "4675322082": {  # Roland Creek Camp — fully booked Jul 16 (breaks mid-chain)
        "2026-07-15": 2,
        "2026-07-16": 0,
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
    "4675322079": {  # May Creek Camp — open most nights
        "2026-07-15": 1,
        "2026-07-16": 2,
        "2026-07-17": 3,
        "2026-07-18": 1,
        "2026-07-19": 2,
        "2026-07-20": 0,
    },
    "4675322072": {  # Devils Creek Camp — fully booked Jul 18 (blocks 4-night chains)
        "2026-07-15": 4,
        "2026-07-16": 3,
        "2026-07-17": 2,
        "2026-07-18": 0,
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
    "4675322_NIGHTMARE": {  # Nightmare Camp — walk-up/in-station only Jul 15–18
        "2026-07-15": -2,
        "2026-07-16": -2,
        "2026-07-17": -2,
        "2026-07-18": -2,
        "2026-07-19": 1,   # opens for online booking Jul 19
        "2026-07-20": 0,
    },
    "4675322_COPPER": {  # Copper Ridge Camp — low but available
        "2026-07-15": 1,
        "2026-07-16": 2,
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
}

# ---------------------------------------------------------------------------
# Facility ID → park name (mirrors PARKS dict in cli.py)
# ---------------------------------------------------------------------------

_FACILITY_NAMES: dict[str, str] = {
    "4675317": "Mount Rainier",
    "4675322": "North Cascades",
    "4098362": "Olympic National Park",
    "445863":  "Enchantments",
}

# ---------------------------------------------------------------------------
# Public API — same signatures as api.py
# ---------------------------------------------------------------------------

def fetch_sites(facility_id: str) -> list[dict]:  # noqa: ARG001
    """
    Return mock sites. facility_id is accepted but ignored.

    All parks use the same synthetic North Cascades East Bank Trail topology
    in mock mode — the graph builder and search engine receive identical
    data structures regardless of which park is selected.

    Each site dict includes a children field listing adjacent division IDs,
    matching the shape returned by api.fetch_sites().
    """
    return list(_SITES)


def fetch_trails(bbox: tuple) -> list[dict]:  # noqa: ARG001
    """Return all three mock trails. bbox is accepted but ignored."""
    return [_EAST_BANK_TRAIL, _NIGHTMARE_LOOP_TRAIL, _COPPER_RIDGE_TRAIL]


def fetch_availability(
    facility_id: str,   # noqa: ARG001
    division_id: str,
    start_date: date,   # noqa: ARG001
    permit_type: str = "ITINERARY",  # noqa: ARG001 — accepted for API compatibility, ignored
) -> dict[str, int]:
    """
    Return mock availability for one site.

    start_date and permit_type are accepted but ignored — mock data covers a
    fixed date window and does not distinguish permit types.
    Returns an empty dict for unknown division IDs.

    Return values follow the same sentinel convention as api.fetch_availability():
      > 0  permits remaining for online booking
        0  fully booked (no permits of any kind)
       -2  walk-up / in-station only (online quota exhausted, station quota remains)
    """
    return dict(_AVAILABILITY.get(division_id, {}))
