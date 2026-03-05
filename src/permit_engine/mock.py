"""
Mock data matching the exact return shapes of api.fetch_sites(),
api.fetch_trails(), and api.fetch_availability().

Used when --live is NOT passed. Drop-in replacement for the api module —
the graph builder and search engine receive identical data structures
regardless of which source is active.

Site data is based on real North Cascades East Bank Trail division IDs and
coordinates sourced from the rec.gov /api/permitcontent/4675322 response
(verified March 2026 HAR export). Availability is synthetic but covers
realistic booking scenarios.

Mock trail topology
-------------------
Three trails are defined to exercise all adjacency scenarios:

  East Bank Trail (linear, 5 camps):
      South TH (node 9001) ── CampA ── CampB ── CampC ── CampD ── North TH (node 9015)
      All within-trail edges are always valid.

  Nightmare Loop Trail (branches off East Bank mid-trail at node 9008):
      node 9008 is a MID-TRAIL node on East Bank Trail (index 5 of 9) AND
      the START node of Nightmare Loop (index 0 of 4).
      → Shared node 9008 is endpoint of Nightmare Loop but mid-trail on East Bank.
      → This is a genuine trail junction. CampC ↔ CampE edge is ALWAYS valid.

  Copper Ridge Trail (shares start node 9001 with East Bank Trail):
      node 9001 is the START node (endpoint) of BOTH East Bank and Copper Ridge.
      → Both trails end at the same parking lot trailhead.
      → CampA ↔ CampF edge is a TRAILHEAD connection.
      → Blocked when allow_trailhead=False, allowed when allow_trailhead=True.
"""
from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Sites — real NC East Bank Trail division IDs and coordinates
# ---------------------------------------------------------------------------

# Real division IDs and GPS coordinates from /api/permitcontent/4675322
# (North Cascades, East Bank Trail district).
_SITES = [
    {
        "division_id": "4675322083",
        "name": "Ruby Pasture Camp",
        "lat": 48.72839,
        "lon": -121.01404,
        "district": "East Bank Trail",
    },
    {
        "division_id": "4675322082",
        "name": "Roland Creek Camp",
        "lat": 48.77136,
        "lon": -121.02096,
        "district": "East Bank Trail",
    },
    {
        "division_id": "4675322079",
        "name": "May Creek Camp",
        "lat": 48.78686,
        "lon": -121.02873,
        "district": "East Bank Trail",
    },
    {
        "division_id": "4675322072",
        "name": "Devils Creek Camp",
        "lat": 48.83771,
        "lon": -121.02015,
        "district": "East Bank Trail",
    },
    # CampE — on Nightmare Loop Trail (genuine mid-trail junction with East Bank)
    {
        "division_id": "4675322_NIGHTMARE",
        "name": "Nightmare Camp",
        "lat": 48.93380,
        "lon": -120.98643,
        "district": "East Bank Trail",
    },
    # CampF — on Copper Ridge Trail (trailhead connection with East Bank)
    {
        "division_id": "4675322_COPPER",
        "name": "Copper Ridge Camp",
        "lat": 48.71000,
        "lon": -121.04800,
        "district": "Copper-Chilliwack",
    },
]

# ---------------------------------------------------------------------------
# Trails — synthetic OSM-shaped data covering all three adjacency scenarios
# ---------------------------------------------------------------------------

# East Bank Trail — linear, runs south to north.
# node 9001 = south trailhead (parking lot), node 9015 = north trailhead.
# Sites snap onto this trail at the nodes nearest their real coordinates.
_EAST_BANK_TRAIL = {
    "osm_id": "100001",
    "name": "East Bank Trail",
    "node_ids": [
        9001,   # south trailhead (endpoint) — near CampF (Copper Ridge TH)
        9002,   # approach
        9003,   # near CampA (Ruby Pasture, 48.7284, -121.0140)
        9004,   # mid-section
        9005,   # near CampB (Roland Creek, 48.7714, -121.0210)
        9006,   # mid-section
        9007,   # near CampC (May Creek, 48.7869, -121.0287)
        9008,   # JUNCTION with Nightmare Loop Trail — mid-trail node on East Bank
        9009,   # near CampD (Devils Creek, 48.8377, -121.0202)
        9010,   # approach to north TH
        9015,   # north trailhead (endpoint)
    ],
    "points": [
        (48.7100, -121.0050),  # 9001 south TH
        (48.7200, -121.0100),  # 9002
        (48.7284, -121.0140),  # 9003 — Ruby Pasture Camp snaps here
        (48.7500, -121.0180),  # 9004
        (48.7714, -121.0210),  # 9005 — Roland Creek Camp snaps here
        (48.7800, -121.0250),  # 9006
        (48.7869, -121.0287),  # 9007 — May Creek Camp snaps here
        (48.8200, -121.0220),  # 9008 — junction node (mid-trail on East Bank)
        (48.8377, -121.0202),  # 9009 — Devils Creek Camp snaps here
        (48.9000, -121.0300),  # 9010
        (48.9500, -121.0380),  # 9015 north TH
    ],
}

# Nightmare Loop Trail — spur branching off East Bank at node 9008 (mid-trail).
# node 9008 is index 0 on Nightmare Loop (its endpoint) but index 7 on East Bank
# (a mid-trail node). Because it is NOT an endpoint of East Bank, this is a
# genuine junction. CampC ↔ CampE is always a valid edge.
_NIGHTMARE_LOOP_TRAIL = {
    "osm_id": "100002",
    "name": "Nightmare Loop Trail",
    "node_ids": [
        9008,   # junction with East Bank Trail (endpoint of Nightmare Loop, mid of East Bank)
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

# Copper Ridge Trail — starts at the SAME parking lot as East Bank Trail
# (both share node 9001 as their first/endpoint node).
# Because node 9001 is an endpoint of BOTH trails, this is a trailhead
# connection. CampA ↔ CampF edge is blocked when allow_trailhead=False.
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
# Designed to produce known chain outcomes for testing.
#
# Scenario summary for 2026-07-15 start:
#   All-available window   : Jul 15–17 (all sites have remaining >= 1)
#   Mid-chain blocked      : Jul 16, Roland Creek = 0 (breaks 2-night chain A→B)
#   Late-trip blocked      : Jul 18, Devils Creek = 0 (blocks 4-night chain)
#   Fully booked day       : Jul 20 (all sites = 0, no chains possible)
_AVAILABILITY: dict[str, dict[str, int]] = {
    "4675322083": {  # Ruby Pasture Camp
        "2026-07-15": 3,
        "2026-07-16": 2,
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 3,
        "2026-07-20": 0,
    },
    "4675322082": {  # Roland Creek Camp
        "2026-07-15": 2,
        "2026-07-16": 0,  # fully booked — breaks chains through here on night of Jul 16
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
    "4675322079": {  # May Creek Camp
        "2026-07-15": 1,
        "2026-07-16": 2,
        "2026-07-17": 3,
        "2026-07-18": 1,
        "2026-07-19": 2,
        "2026-07-20": 0,
    },
    "4675322072": {  # Devils Creek Camp
        "2026-07-15": 4,
        "2026-07-16": 3,
        "2026-07-17": 2,
        "2026-07-18": 0,  # fully booked — blocks 4-night chains ending here
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
    "4675322_NIGHTMARE": {  # Nightmare Camp
        "2026-07-15": 2,
        "2026-07-16": 1,
        "2026-07-17": 2,
        "2026-07-18": 1,
        "2026-07-19": 2,
        "2026-07-20": 0,
    },
    "4675322_COPPER": {  # Copper Ridge Camp
        "2026-07-15": 1,
        "2026-07-16": 2,
        "2026-07-17": 1,
        "2026-07-18": 2,
        "2026-07-19": 1,
        "2026-07-20": 0,
    },
}

# ---------------------------------------------------------------------------
# Public API — same signatures as api.py
# ---------------------------------------------------------------------------

def fetch_sites(facility_id: str) -> list[dict]:  # noqa: ARG001
    """Return mock sites. facility_id is accepted but ignored."""
    return list(_SITES)


def fetch_trails(bbox: tuple) -> list[dict]:  # noqa: ARG001
    """Return all three mock trails. bbox is accepted but ignored."""
    return [_EAST_BANK_TRAIL, _NIGHTMARE_LOOP_TRAIL, _COPPER_RIDGE_TRAIL]


def fetch_availability(
    facility_id: str,  # noqa: ARG001
    division_id: str,
    start_date: date,  # noqa: ARG001
) -> dict[str, int]:
    """
    Return mock availability for one site.

    start_date is accepted but ignored — mock data covers a fixed date window.
    Returns an empty dict for unknown division IDs.
    """
    return dict(_AVAILABILITY.get(division_id, {}))
