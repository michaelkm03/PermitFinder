"""
Shared pytest fixtures.

All fixtures are built from the mock module so tests never make network calls.

Trail topology (see mock.py for node-level diagram):
  East Bank Trail (linear):
      South TH (9001) -- CampA -- CampB -- CampC -- CampD -- North TH (9015)

  Nightmare Loop Trail (genuine mid-trail junction at node 9008):
      node 9008 is mid-trail on East Bank AND endpoint of Nightmare Loop.
      CampC <-> CampE edge is ALWAYS valid (genuine junction, not trailhead).

  Copper Ridge Trail (shared parking-lot trailhead at node 9001):
      node 9001 is endpoint of BOTH East Bank and Copper Ridge.
      CampA <-> CampF edge is a TRAILHEAD connection:
        blocked when allow_trailhead=False, allowed when allow_trailhead=True.
"""
import pytest
from permit_engine import mock


@pytest.fixture()
def raw_sites():
    """All mock sites (6 camps across 3 trails)."""
    return mock.fetch_sites("any")


@pytest.fixture()
def raw_trails():
    """All three mock trails."""
    return mock.fetch_trails(())


@pytest.fixture()
def availability():
    """Mock availability for all sites across the test date window."""
    sites = mock.fetch_sites("any")
    from datetime import date
    return {
        s["division_id"]: mock.fetch_availability("any", s["division_id"], date(2026, 7, 15))
        for s in sites
    }
