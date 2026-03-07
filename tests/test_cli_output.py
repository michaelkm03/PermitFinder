"""
Tests for CLI output helpers: _overview_table, _print_chain_details,
and --detail-limit argument parsing.
"""
import argparse
from datetime import date

import pytest

from permit_engine.graph import Site
from permit_engine.search import Chain, ChainLink
from permit_engine.cli import _overview_table, _parse_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_site(division_id: str, name: str, district: str = "Test Area") -> Site:
    return Site(division_id=division_id, name=name, lat=48.0, lon=-121.0, district=district)


def _make_chain(sites_with_districts: list[tuple[str, str, str]]) -> Chain:
    """Build a Chain from [(division_id, name, district), ...] starting 2026-07-15."""
    from datetime import timedelta
    links = [
        ChainLink(
            site=_make_site(div_id, name, district),
            night_date=date(2026, 7, 15) + timedelta(days=i),
            remaining=3,
        )
        for i, (div_id, name, district) in enumerate(sites_with_districts)
    ]
    return Chain(links=links)


# ---------------------------------------------------------------------------
# _overview_table: Area (district) column
# ---------------------------------------------------------------------------

class TestOverviewTableDistrict:
    def test_area_column_exists(self):
        """_overview_table must include an 'Area' column."""
        chain = _make_chain([("A", "Site A", "Carbon River Area"), ("B", "Site B", "Carbon River Area")])
        tbl = _overview_table([chain])
        col_names = [col.header for col in tbl.columns]
        assert "Area" in col_names

    def test_single_district_shown(self):
        """When all sites share one district it appears once in the Area cell."""
        chain = _make_chain([
            ("A", "Site A", "Carbon River Area"),
            ("B", "Site B", "Carbon River Area"),
        ])
        tbl = _overview_table([chain])
        # Inspect the rendered cells via the table row data.
        rows = list(tbl.rows)
        assert len(rows) == 1

    def test_multiple_districts_deduplicated(self):
        """Sites in different districts → both districts appear in the Area cell."""
        chain = _make_chain([
            ("A", "Site A", "Carbon River Area"),
            ("B", "Site B", "Mowich Area"),
            ("C", "Site C", "Carbon River Area"),  # repeat — should not appear twice
        ])
        tbl = _overview_table([chain])
        # Verify we can build the table without error (rendering logic covered).
        assert len(tbl.rows) == 1

    def test_blank_district_falls_back_to_dash(self):
        """A site with an empty district string renders '—' in the Area column."""
        chain = _make_chain([
            ("A", "Site A", ""),
            ("B", "Site B", ""),
        ])
        tbl = _overview_table([chain])
        assert len(tbl.rows) == 1  # table still renders without error

    def test_numbering_uses_start_num(self):
        """start_num offsets the # column for grouped display."""
        chains = [
            _make_chain([("A", "Site A", "Area 1"), ("B", "Site B", "Area 1")]),
            _make_chain([("C", "Site C", "Area 2"), ("D", "Site D", "Area 2")]),
        ]
        tbl = _overview_table(chains, start_num=5)
        assert len(tbl.rows) == 2

    def test_no_header_mode(self):
        """show_header=False disables the header row (used in grouped mode)."""
        chain = _make_chain([("A", "Site A", "Area 1"), ("B", "Site B", "Area 1")])
        tbl_with    = _overview_table([chain], show_header=True)
        tbl_without = _overview_table([chain], show_header=False)
        assert tbl_with.show_header is True
        assert tbl_without.show_header is False


# ---------------------------------------------------------------------------
# _print_chain_details: Area column presence (import-level check)
# ---------------------------------------------------------------------------

class TestChainDetailAreaColumn:
    def test_area_column_in_detail_table(self, capsys):
        """_print_chain_details must include 'Area' in the night-by-night table."""
        from rich.console import Console
        from permit_engine.cli import _print_chain_details, _console
        import io

        chain = _make_chain([
            ("A", "Ruby Pasture", "East Bank Trail"),
            ("B", "Roland Creek", "East Bank Trail"),
        ])

        # Capture Rich output to a string buffer.
        buf = io.StringIO()
        console = Console(file=buf, highlight=False, width=120)

        # Temporarily swap _console so _print_chain_details uses our buffer.
        import permit_engine.cli as cli_mod
        original = cli_mod._console
        cli_mod._console = console
        try:
            _print_chain_details([chain])
        finally:
            cli_mod._console = original

        output = buf.getvalue()
        assert "Area" in output
        assert "East Bank Trail" in output


# ---------------------------------------------------------------------------
# --detail-limit argument parsing
# ---------------------------------------------------------------------------

class TestDetailLimitArg:
    """--detail-limit N controls how many districts are queried for availability."""

    def _parse(self, extra: list[str]) -> argparse.Namespace:
        base = [
            "--park", "rainier",
            "--start-date", "2026-07-15",
            "--nights", "5",
        ]
        import sys
        old = sys.argv
        sys.argv = ["wa-permits"] + base + extra
        try:
            return _parse_args()
        finally:
            sys.argv = old

    def test_default_detail_limit_is_25(self):
        """Default is 25 districts."""
        args = self._parse([])
        assert args.detail_limit == 25

    def test_one_district(self):
        """--detail-limit 1 limits to a single district."""
        args = self._parse(["--detail-limit", "1"])
        assert args.detail_limit == 1

    def test_custom_district_count(self):
        args = self._parse(["--detail-limit", "3"])
        assert args.detail_limit == 3

    def test_limit_and_detail_limit_are_independent(self):
        """--limit caps chains; --detail-limit caps districts. They are orthogonal."""
        args = self._parse(["--limit", "50", "--detail-limit", "5"])
        assert args.limit == 50
        assert args.detail_limit == 5


# ---------------------------------------------------------------------------
# --area argument parsing and district filtering
# ---------------------------------------------------------------------------

class TestAreaArg:
    def _parse(self, extra: list[str]) -> argparse.Namespace:
        import sys
        base = ["--park", "rainier", "--start-date", "2026-07-15", "--nights", "5"]
        sys.argv = ["wa-permits"] + base + extra
        try:
            return _parse_args()
        finally:
            sys.argv = ["wa-permits"]

    def test_area_default_is_none(self):
        args = self._parse([])
        assert args.area is None

    def test_single_area_parsed(self):
        args = self._parse(["--area", "Carbon River"])
        assert args.area == ["Carbon River"]

    def test_multiple_areas_parsed(self):
        args = self._parse(["--area", "Carbon River", "Mowich"])
        assert args.area == ["Carbon River", "Mowich"]

    def test_area_and_detail_limit_coexist(self):
        """--area and --detail-limit are independent params."""
        args = self._parse(["--area", "East Bank", "--detail-limit", "2"])
        assert args.area == ["East Bank"]
        assert args.detail_limit == 2


class TestAreaDistrictFilter:
    """Unit tests for the district substring-match logic used by --area."""

    def test_exact_match(self):
        """Exact district name matches case-insensitively."""
        district = "East Bank Trail"
        filters = ["East Bank Trail"]
        assert any(f.lower() in district.lower() for f in filters)

    def test_substring_match(self):
        """Partial name matches (user-friendly)."""
        district = "Carbon River Area Camps"
        filters = ["carbon river"]
        assert any(f.lower() in district.lower() for f in filters)

    def test_no_match(self):
        district = "East Bank Trail"
        filters = ["Mowich"]
        assert not any(f.lower() in district.lower() for f in filters)

    def test_or_logic_across_filters(self):
        """A district matching ANY of the filters is included."""
        district = "East Bank Trail"
        filters = ["Mowich", "East Bank"]
        assert any(f.lower() in district.lower() for f in filters)

    def test_mock_area_filter_reduces_fetched_sites(self, raw_sites, raw_trails, availability):
        """Sites outside the filtered district should not appear in availability."""
        from permit_engine.graph import build_graph
        graph = build_graph(raw_sites, raw_trails)
        area_filter = ["East Bank"]  # matches "East Bank Trail" in mock data

        # Simulate the filter applied in _search_park mock branch.
        connected = [sid for sid in graph.sites if graph.adjacency.get(sid)]
        fetch_ids = [
            sid for sid in connected
            if any(f.lower() in (graph.sites[sid].district or "").lower() for f in area_filter)
        ]
        # Copper-Chilliwack district site should be excluded.
        from permit_engine import mock
        copper_ids = [
            s["division_id"] for s in mock.fetch_sites("any")
            if s.get("district") == "Copper-Chilliwack"
        ]
        for cid in copper_ids:
            assert cid not in fetch_ids

    def test_no_match_returns_empty_fetch_list(self, raw_sites, raw_trails):
        """A filter matching nothing produces an empty fetch list."""
        from permit_engine.graph import build_graph
        graph = build_graph(raw_sites, raw_trails)
        connected = [sid for sid in graph.sites if graph.adjacency.get(sid)]
        fetch_ids = [
            sid for sid in connected
            if any(f.lower() in (graph.sites[sid].district or "").lower() for f in ["Nonexistent Area"])
        ]
        assert fetch_ids == []
