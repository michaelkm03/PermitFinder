"""
Tests for the Chain and ChainLink dataclasses in search.py.

Chain is the core return type of find_chains(). These tests verify its
computed properties independently of the DFS logic.
"""
from datetime import date

from permit_engine.graph import Site
from permit_engine.search import Chain, ChainLink


def _make_link(site_id: str, night_offset: int, remaining: int) -> ChainLink:
    """Build a minimal ChainLink for testing."""
    site = Site(
        division_id=site_id,
        name=f"Site {site_id}",
        lat=48.0,
        lon=-121.0,
        district="Test",
    )
    return ChainLink(
        site=site,
        night_date=date(2026, 7, 15) + __import__("datetime").timedelta(days=night_offset),
        remaining=remaining,
    )


def _make_chain(remainders: list[int]) -> Chain:
    """Build a Chain with len(remainders) links, one per night from 2026-07-15."""
    links = [_make_link(str(i), i, r) for i, r in enumerate(remainders)]
    return Chain(links=links)


# ---------------------------------------------------------------------------
# Date properties
# ---------------------------------------------------------------------------

class TestChainDateProperties:
    def test_start_date_is_first_link_date(self):
        chain = _make_chain([3, 2, 1])
        assert chain.start_date == date(2026, 7, 15)

    def test_end_date_is_last_link_date(self):
        chain = _make_chain([3, 2, 1])
        assert chain.end_date == date(2026, 7, 17)

    def test_num_nights_equals_link_count(self):
        chain = _make_chain([3, 2, 1])
        assert chain.num_nights == 3


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------

class TestChainAvailability:
    def test_min_remaining_returns_lowest_count(self):
        chain = _make_chain([5, 1, 3])
        assert chain.min_remaining() == 1

    def test_min_remaining_returns_negative_one_when_any_unknown(self):
        """A single -1 (not fetched) makes the whole chain unknown."""
        chain = _make_chain([3, -1, 2])
        assert chain.min_remaining() == -1

    def test_meets_permit_count(self):
        assert _make_chain([3, 2, 4]).meets_permit_count(2) is True   # all above
        assert _make_chain([3, 1, 4]).meets_permit_count(2) is False  # one below
