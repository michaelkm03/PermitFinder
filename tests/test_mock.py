"""
Tests for the mock data module (mock.py).

Verifies that mock.fetch_sites() and mock.fetch_availability() return data
in the exact shape expected by build_graph() and find_chains(). All tests
are fully offline.
"""
from datetime import date

from permit_engine import mock

REQUIRED_SITE_KEYS = {"division_id", "name", "lat", "lon", "district", "children"}


class TestFetchSites:
    def test_returns_six_sites(self):
        """Mock dataset has exactly 6 camps."""
        sites = mock.fetch_sites("any")
        assert len(sites) == 6

    def test_each_site_has_required_keys(self):
        for site in mock.fetch_sites("any"):
            assert REQUIRED_SITE_KEYS <= set(site.keys()), (
                f"Site missing keys: {REQUIRED_SITE_KEYS - set(site.keys())}"
            )

    def test_children_are_lists(self):
        """Every site's children field must be a list (possibly empty)."""
        for site in mock.fetch_sites("any"):
            assert isinstance(site["children"], list), (
                f"Site {site['division_id']} children is not a list"
            )

    def test_isolated_site_has_empty_children(self):
        """Copper Ridge Camp has no children (isolated node)."""
        sites = {s["division_id"]: s for s in mock.fetch_sites("any")}
        assert sites["4675322_COPPER"]["children"] == []

    def test_linear_chain_children_symmetric(self):
        """Each consecutive pair on East Bank must reference each other in children."""
        sites = {s["division_id"]: s for s in mock.fetch_sites("any")}
        pairs = [
            ("4675322083", "4675322082"),  # Ruby → Roland
            ("4675322082", "4675322079"),  # Roland → May Creek
            ("4675322079", "4675322072"),  # May Creek → Devils
        ]
        for id_a, id_b in pairs:
            assert id_b in sites[id_a]["children"], f"{id_a} missing child {id_b}"
            assert id_a in sites[id_b]["children"], f"{id_b} missing child {id_a}"


class TestFetchAvailability:
    def test_known_site_returns_expected_count(self):
        """Ruby Pasture has remaining=3 on 2026-07-15 per mock data."""
        avail = mock.fetch_availability("any", "4675322083", date(2026, 7, 15))
        assert avail.get("2026-07-15") == 3

    def test_unknown_site_returns_empty_dict(self):
        """Unknown division_id must return {} — no data, not an error."""
        avail = mock.fetch_availability("any", "UNKNOWN_ID", date(2026, 7, 15))
        assert avail == {}

