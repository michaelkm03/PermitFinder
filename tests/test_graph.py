"""
Tests for graph.build_graph() — site snapping, adjacency correctness,
and all trailhead connection scenarios.

Trail topology used in these tests (see conftest.py for diagram):
  CampA = Ruby Pasture     (East Bank Trail)
  CampB = Roland Creek     (East Bank Trail)
  CampC = May Creek        (East Bank Trail)
  CampD = Devils Creek     (East Bank Trail)
  CampE = Nightmare Camp   (Nightmare Loop — genuine junction at node 9008)
  CampF = Copper Ridge     (Copper Ridge   — shared trailhead at node 9001)
"""
import pytest
from permit_engine.graph import build_graph

CAMP_A = "4675322083"         # Ruby Pasture   — southernmost East Bank camp
CAMP_B = "4675322082"         # Roland Creek
CAMP_C = "4675322079"         # May Creek
CAMP_D = "4675322072"         # Devils Creek   — northernmost East Bank camp
CAMP_E = "4675322_NIGHTMARE"  # on Nightmare Loop (genuine junction with East Bank)
CAMP_F = "4675322_COPPER"     # on Copper Ridge   (trailhead connection with East Bank)


# ---------------------------------------------------------------------------
# Basic graph structure
# ---------------------------------------------------------------------------

class TestGraphNodes:
    def test_all_sites_present_as_nodes(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert set(graph.sites.keys()) == {CAMP_A, CAMP_B, CAMP_C, CAMP_D, CAMP_E, CAMP_F}

    def test_site_has_correct_name(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert graph.sites[CAMP_A].name == "Ruby Pasture Camp"
        assert graph.sites[CAMP_D].name == "Devils Creek Camp"

    def test_site_has_correct_coordinates(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        site = graph.sites[CAMP_A]
        assert abs(site.lat - 48.72839) < 0.0001
        assert abs(site.lon - (-121.01404)) < 0.0001


# ---------------------------------------------------------------------------
# Within-trail edges (East Bank Trail — linear sequence A-B-C-D)
# ---------------------------------------------------------------------------

class TestWithinTrailEdges:
    """Consecutive sites on the same trail are always adjacent."""

    def test_consecutive_camps_share_an_edge(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert CAMP_B in graph.adjacency[CAMP_A]
        assert CAMP_A in graph.adjacency[CAMP_B]

    def test_edges_are_bidirectional(self, raw_sites, raw_trails):
        """Every edge A→B must also exist as B→A."""
        graph = build_graph(raw_sites, raw_trails)
        for div_id, neighbors in graph.adjacency.items():
            for neighbor_id in neighbors:
                assert div_id in graph.adjacency[neighbor_id], (
                    f"Edge {div_id}→{neighbor_id} exists but reverse does not"
                )

    def test_non_consecutive_east_bank_camps_have_no_direct_edge(self, raw_sites, raw_trails):
        """CampA and CampD are not consecutive on East Bank — no direct edge."""
        graph = build_graph(raw_sites, raw_trails)
        assert CAMP_D not in graph.adjacency[CAMP_A]
        assert CAMP_A not in graph.adjacency[CAMP_D]

    def test_camp_a_connects_only_to_camp_b_on_east_bank(self, raw_sites, raw_trails):
        """CampA has exactly one East Bank neighbor: CampB (no skip-adjacency)."""
        graph = build_graph(raw_sites, raw_trails)
        east_bank_camps = {CAMP_A, CAMP_B, CAMP_C, CAMP_D}
        east_bank_neighbors_of_a = east_bank_camps & set(graph.adjacency[CAMP_A])
        assert east_bank_neighbors_of_a == {CAMP_B}

    def test_adjacency_lists_are_sorted(self, raw_sites, raw_trails):
        """Sorted adjacency lists make output and tests deterministic."""
        graph = build_graph(raw_sites, raw_trails)
        for div_id, neighbors in graph.adjacency.items():
            assert neighbors == sorted(neighbors), (
                f"adjacency[{div_id}] is not in sorted order"
            )


# ---------------------------------------------------------------------------
# N-adjacent nodes — junction camp with 3+ neighbors
# ---------------------------------------------------------------------------

class TestNAdjacentNodes:
    """A site at a trail junction accumulates edges from all connected trails."""

    def test_east_bank_camp_connects_to_nightmare_loop_via_junction(
        self, raw_sites, raw_trails
    ):
        """
        Node 9008 is a mid-trail node on East Bank (index 7 of 11) and the
        start endpoint of Nightmare Loop (index 0 of 4).

        CampD (Devils Creek) is the East Bank camp nearest to the junction side
        of 9008. CampE (Nightmare Camp) is on Nightmare Loop.

        Because 9008 is mid-trail on East Bank, this is a genuine junction
        and the cross-trail edge must always exist.
        """
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        # CampE must be reachable from at least one East Bank camp near the junction.
        reachable_from_east_bank = any(
            CAMP_E in graph.adjacency.get(eb_id, [])
            for eb_id in [CAMP_C, CAMP_D]
        )
        assert reachable_from_east_bank, (
            "Nightmare Camp must be reachable from East Bank via the genuine junction"
        )

    def test_junction_camp_has_degree_at_least_three(self, raw_sites, raw_trails):
        """
        The East Bank camp nearest the junction (CampD or CampC) connects to
        its East Bank neighbor(s) plus CampE via Nightmare Loop — degree >= 3
        for the camp that sits at the junction side.
        """
        graph = build_graph(raw_sites, raw_trails)
        # Collect the degrees of the camps around the junction area
        junction_area_camps = [CAMP_C, CAMP_D]
        max_degree = max(len(graph.adjacency[c]) for c in junction_area_camps)
        assert max_degree >= 3, (
            "The camp at or near the Nightmare Loop junction should have degree >= 3"
        )


# ---------------------------------------------------------------------------
# Scenario: genuine trail junction (always valid, trailhead flag irrelevant)
# ---------------------------------------------------------------------------

class TestGenuineJunction:
    """
    Node 9008 is the endpoint of Nightmare Loop BUT mid-trail on East Bank.
    Because it is not an endpoint of East Bank, it is a genuine junction,
    not a trailhead connection. The cross-trail edge is valid regardless of
    the allow_trailhead flag.
    """

    def test_genuine_junction_allowed_when_trailhead_flag_off(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        reachable = any(
            CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D]
        )
        assert reachable

    def test_genuine_junction_allowed_when_trailhead_flag_on(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=True)
        reachable = any(
            CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D]
        )
        assert reachable


# ---------------------------------------------------------------------------
# Scenario: trailhead connection (shared parking-lot endpoint)
# ---------------------------------------------------------------------------

class TestTrailheadConnection:
    """
    Node 9001 is the first (endpoint) node of BOTH East Bank Trail and Copper
    Ridge Trail — both trails begin at the same parking lot.
    CampA (East Bank) and CampF (Copper Ridge) are the nearest sites.
    This is a trailhead connection: a hiker must cross the parking lot.
    """

    def test_trailhead_connection_is_excluded_by_default(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        assert CAMP_F not in graph.adjacency[CAMP_A], (
            "CampF must not connect to CampA when --trailhead is off"
        )
        assert CAMP_A not in graph.adjacency[CAMP_F]

    def test_trailhead_connection_is_included_when_flag_is_set(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=True)
        assert CAMP_F in graph.adjacency[CAMP_A], (
            "CampF must connect to CampA when --trailhead is on"
        )
        assert CAMP_A in graph.adjacency[CAMP_F]

    def test_trailhead_flag_does_not_remove_within_trail_edges(self, raw_sites, raw_trails):
        """Turning off trailhead connections must not affect within-trail edges."""
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        for id_a, id_b in [(CAMP_A, CAMP_B), (CAMP_B, CAMP_C), (CAMP_C, CAMP_D)]:
            assert id_b in graph.adjacency[id_a], (
                f"Within-trail edge {id_a}↔{id_b} must exist even with trailhead off"
            )

    def test_trailhead_flag_does_not_remove_genuine_junction(self, raw_sites, raw_trails):
        """Disabling trailhead connections must not remove the Nightmare Loop junction."""
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        reachable = any(
            CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D]
        )
        assert reachable, (
            "Genuine junction to Nightmare Camp must be unaffected by --trailhead flag"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_site_far_from_all_trails_has_no_edges(self, raw_trails):
        """A site with coordinates nowhere near any trail is an isolated node."""
        far_site = [{
            "division_id": "FAR001",
            "name": "Remote Camp",
            "lat": 47.0000,   # far south of all mock trails (min mock lat is ~48.7)
            "lon": -120.0000,
            "district": "Unknown",
        }]
        graph = build_graph(far_site, raw_trails)
        assert graph.adjacency["FAR001"] == []

    def test_no_trails_produces_isolated_nodes(self, raw_sites):
        """Without trail data every site is an isolated node with no edges."""
        graph = build_graph(raw_sites, [])
        assert set(graph.sites.keys()) == {CAMP_A, CAMP_B, CAMP_C, CAMP_D, CAMP_E, CAMP_F}
        for neighbors in graph.adjacency.values():
            assert neighbors == []

    def test_single_site_on_trail_produces_no_edges(self, raw_trails):
        """One site on a trail cannot form an edge — need at least two."""
        only_one = [{
            "division_id": CAMP_A,
            "name": "Ruby Pasture Camp",
            "lat": 48.72839,
            "lon": -121.01404,
            "district": "East Bank Trail",
        }]
        graph = build_graph(only_one, raw_trails)
        assert graph.adjacency[CAMP_A] == []
