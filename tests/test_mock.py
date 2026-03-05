"""
Tests for the mock data module (mock.py).

Verifies that mock.fetch_sites(), mock.fetch_trails(), and
mock.fetch_availability() return data in the exact shape expected by
build_graph() and find_chains(). All tests are fully offline.
"""
from datetime import date

from permit_engine import mock

REQUIRED_SITE_KEYS   = {"division_id", "name", "lat", "lon", "district"}
REQUIRED_TRAIL_KEYS  = {"osm_id", "name", "node_ids", "points"}


class TestFetchSites:
    def test_returns_six_sites(self):
        """Mock dataset has exactly 6 camps across 3 trails."""
        sites = mock.fetch_sites("any")
        assert len(sites) == 6

    def test_each_site_has_required_keys(self):
        for site in mock.fetch_sites("any"):
            assert REQUIRED_SITE_KEYS <= set(site.keys()), (
                f"Site missing keys: {REQUIRED_SITE_KEYS - set(site.keys())}"
            )

class TestFetchTrails:
    def test_returns_three_trails(self):
        """Mock has East Bank, Nightmare Loop, and Copper Ridge trails."""
        trails = mock.fetch_trails(())
        assert len(trails) == 3

    def test_node_ids_and_points_same_length(self):
        """Every node_id must have a matching (lat, lon) point."""
        for trail in mock.fetch_trails(()):
            assert len(trail["node_ids"]) == len(trail["points"]), (
                f"Trail '{trail['name']}': node_ids and points length mismatch"
            )


class TestFetchAvailability:
    def test_known_site_returns_expected_count(self):
        """Ruby Pasture has remaining=3 on 2026-07-15 per mock data."""
        avail = mock.fetch_availability("any", "4675322083", date(2026, 7, 15))
        assert avail.get("2026-07-15") == 3

    def test_unknown_site_returns_empty_dict(self):
        """Unknown division_id must return {} — no data, not an error."""
        avail = mock.fetch_availability("any", "UNKNOWN_ID", date(2026, 7, 15))
        assert avail == {}

