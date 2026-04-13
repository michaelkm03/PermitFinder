"""
Tests for search.find_chains() and search.filter_by_availability().

All tests use mock data so no network calls are made. Availability values
are defined in mock.py — tests reference specific dates and expected counts
documented there.

Mock availability summary (relevant dates):
  2026-07-15:  Ruby=3, Roland=2, MayCreek=1, Devils=4  — all sites open
  2026-07-16:  Ruby=2, Roland=0, MayCreek=2, Devils=3  — Roland fully booked
  2026-07-17:  Ruby=1, Roland=1, MayCreek=3, Devils=2  — all open again
  2026-07-18:  Ruby=2, Roland=2, MayCreek=1, Devils=0  — Devils fully booked
  2026-07-20:  all sites = 0                            — nothing available
"""
import pytest
from datetime import date

from permit_engine.graph import build_graph
from permit_engine.search import Chain, filter_by_availability, find_chains

CAMP_A = "4675322083"         # Ruby Pasture
CAMP_B = "4675322082"         # Roland Creek
CAMP_C = "4675322079"         # May Creek
CAMP_D = "4675322072"         # Devils Creek
CAMP_E = "4675322_NIGHTMARE"  # Nightmare Camp
CAMP_F = "4675322_COPPER"     # Copper Ridge Camp

START = date(2026, 7, 15)


@pytest.fixture()
def graph(raw_sites, raw_trails):
    return build_graph(raw_sites, raw_trails, allow_trailhead=False)


@pytest.fixture()
def graph_with_trailhead(raw_sites, raw_trails):
    return build_graph(raw_sites, raw_trails, allow_trailhead=True)


# ---------------------------------------------------------------------------
# Basic chain finding
# ---------------------------------------------------------------------------

class TestFindChains:
    def test_finds_chains_of_correct_length(self, graph, availability):
        chains = find_chains(graph, availability, START, nights=2)
        assert all(c.num_nights == 2 for c in chains)

    def test_returns_nonempty_results_when_sites_available(self, graph, availability):
        chains = find_chains(graph, availability, START, nights=2)
        assert len(chains) > 0

    def test_every_link_has_annotated_availability(self, graph, availability):
        """Every ChainLink must have a remaining count fetched from the mock data."""
        chains = find_chains(graph, availability, START, nights=2)
        for chain in chains:
            for link in chain.links:
                assert link.remaining != -1, (
                    f"Link {link.site.name} on {link.night_date} has no availability data"
                )

    def test_consecutive_links_use_consecutive_dates(self, graph, availability):
        """Night 2 must be exactly 1 day after Night 1, and so on."""
        from datetime import timedelta
        chains = find_chains(graph, availability, START, nights=3)
        for chain in chains:
            for i in range(1, len(chain.links)):
                delta = chain.links[i].night_date - chain.links[i - 1].night_date
                assert delta.days == 1

    def test_no_site_repeats_within_a_chain(self, graph, availability):
        """A site must not appear twice in the same chain."""
        chains = find_chains(graph, availability, START, nights=3)
        for chain in chains:
            site_ids = [link.site.division_id for link in chain.links]
            assert len(site_ids) == len(set(site_ids)), (
                f"Repeated site in chain: {site_ids}"
            )

    def test_consecutive_chain_sites_are_adjacent_in_graph(self, graph, availability):
        """Each consecutive site pair in a chain must be an edge in the graph."""
        chains = find_chains(graph, availability, START, nights=3)
        for chain in chains:
            for i in range(len(chain.links) - 1):
                id_a = chain.links[i].site.division_id
                id_b = chain.links[i + 1].site.division_id
                assert id_b in graph.adjacency[id_a], (
                    f"Chain contains non-adjacent pair: {id_a} → {id_b}"
                )

    def test_chain_start_date_matches_requested_start(self, graph, availability):
        chains = find_chains(graph, availability, START, nights=2)
        for chain in chains:
            assert chain.start_date == START

    def test_one_night_chain_is_a_single_site(self, graph, availability):
        chains = find_chains(graph, availability, START, nights=1)
        assert all(c.num_nights == 1 for c in chains)
        assert len(chains) == len(graph.sites)  # every site is a 1-night chain


# ---------------------------------------------------------------------------
# Availability annotation on individual nights
# ---------------------------------------------------------------------------

class TestAvailabilityAnnotation:
    def test_roland_creek_shows_zero_on_jul_16(self, graph, availability):
        """Roland Creek is fully booked on 2026-07-16 per mock data."""
        night2_date = date(2026, 7, 16)
        chains = find_chains(graph, availability, START, nights=2)
        roland_on_night2 = [
            link
            for chain in chains
            for link in chain.links
            if link.site.division_id == CAMP_B and link.night_date == night2_date
        ]
        for link in roland_on_night2:
            assert link.remaining == 0

    def test_ruby_pasture_shows_correct_count_on_jul_15(self, graph, availability):
        """Ruby Pasture has remaining=3 on 2026-07-15 per mock data."""
        chains = find_chains(graph, availability, START, nights=1)
        ruby_on_night1 = [
            link
            for chain in chains
            for link in chain.links
            if link.site.division_id == CAMP_A and link.night_date == START
        ]
        assert any(link.remaining == 3 for link in ruby_on_night1)


# ---------------------------------------------------------------------------
# filter_by_availability
# ---------------------------------------------------------------------------

class TestFilterByAvailability:
    def test_chains_with_zero_availability_are_filtered(self, graph, availability):
        """Chains with any night at 0 are removed when permit_count=1."""
        chains = find_chains(graph, availability, START, nights=2)
        filtered = filter_by_availability(chains, permit_count=1)
        for chain in filtered:
            assert chain.meets_permit_count(1)
            assert all(link.remaining >= 1 for link in chain.links)

    def test_higher_permit_count_removes_more_chains(self, graph, availability):
        """Requiring 3 permits filters out more chains than requiring 1."""
        chains = find_chains(graph, availability, START, nights=2)
        filtered_1 = filter_by_availability(chains, permit_count=1)
        filtered_3 = filter_by_availability(chains, permit_count=3)
        assert len(filtered_3) <= len(filtered_1)

    def test_permit_count_exceeding_all_availability_returns_empty(self, graph, availability):
        """No chain can satisfy permit_count=100 — filter returns empty list."""
        chains = find_chains(graph, availability, START, nights=2)
        filtered = filter_by_availability(chains, permit_count=100)
        assert filtered == []

    def test_filter_does_not_modify_original_list(self, graph, availability):
        """filter_by_availability must return a new list, not modify the input."""
        chains = find_chains(graph, availability, START, nights=2)
        original_len = len(chains)
        filter_by_availability(chains, permit_count=3)
        assert len(chains) == original_len

    def test_zero_permit_count_excludes_walkup_chains(self, graph, availability):
        """permit_count=0 requires remaining >= 0 online; walk-up nights (-2) do not pass."""
        chains = find_chains(graph, availability, START, nights=2)
        filtered = filter_by_availability(chains, permit_count=0)
        # No filtered chain may contain a walk-up (-2) night.
        for chain in filtered:
            for link in chain.links:
                assert link.remaining >= 0, (
                    f"Walk-up night should not pass permit_count=0: {chain}"
                )
        # The count of excluded chains equals exactly those with a walk-up night.
        walkup_chains = [c for c in chains if any(lk.remaining == -2 for lk in c.links)]
        assert len(filtered) == len(chains) - len(walkup_chains)


# ---------------------------------------------------------------------------
# Fully booked day
# ---------------------------------------------------------------------------

class TestFullyBooked:
    def test_no_chains_when_start_date_fully_booked(self, graph):
        """2026-07-20 has remaining=0 at every site — no chains possible."""
        from permit_engine import mock
        fully_booked_date = date(2026, 7, 20)
        availability = {
            s["division_id"]: mock.fetch_availability("any", s["division_id"], fully_booked_date)
            for s in mock.fetch_sites("any")
        }
        chains = find_chains(graph, availability, fully_booked_date, nights=1)
        # All 1-night chains exist as nodes, but filtered availability gives 0
        filtered = filter_by_availability(chains, permit_count=1)
        assert filtered == []


# ---------------------------------------------------------------------------
# Trailhead flag integration with search
# ---------------------------------------------------------------------------

class TestTrailheadWithSearch:
    def test_trailhead_enabled_produces_more_or_equal_chains(
        self, raw_sites, raw_trails, availability
    ):
        """Adding trailhead connections can only add edges, never remove them."""
        graph_off = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        graph_on  = build_graph(raw_sites, raw_trails, allow_trailhead=True)
        chains_off = find_chains(graph_off, availability, START, nights=2)
        chains_on  = find_chains(graph_on,  availability, START, nights=2)
        assert len(chains_on) >= len(chains_off)

    def test_copper_ridge_unreachable_without_trailhead_flag(self, graph, availability):
        """
        CampF connects to the graph only via the trailhead at node 9001.
        Without the flag it is isolated and cannot appear in any chain.
        """
        chains = find_chains(graph, availability, START, nights=2)
        copper_in_any_chain = any(
            any(link.site.division_id == CAMP_F for link in chain.links)
            for chain in chains
        )
        assert not copper_in_any_chain

    def test_copper_ridge_reachable_with_trailhead_flag(
        self, graph_with_trailhead, availability
    ):
        chains = find_chains(graph_with_trailhead, availability, START, nights=2)
        copper_in_any_chain = any(
            any(link.site.division_id == CAMP_F for link in chain.links)
            for chain in chains
        )
        assert copper_in_any_chain

