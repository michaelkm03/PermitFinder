"""
Tests for graph.build_graph() — GPS snap to OSM trails, adjacency, trailhead logic.

Trail topology used in these tests (see conftest.py for diagram):
  CampA = Ruby Pasture     (East Bank Trail)
  CampB = Roland Creek     (East Bank Trail)
  CampC = May Creek        (East Bank Trail)
  CampD = Devils Creek     (East Bank Trail)
  CampE = Nightmare Camp   (Nightmare Loop — genuine junction at node 9008)
  CampF = Copper Ridge     (Copper Ridge   — trailhead connection at node 9001)
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

    def test_site_has_correct_district(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert graph.sites[CAMP_A].district == "East Bank Trail"
        assert graph.sites[CAMP_F].district == "Copper-Chilliwack"


# ---------------------------------------------------------------------------
# Within-trail edges (East Bank Trail — linear A-B-C-D)
# ---------------------------------------------------------------------------

class TestWithinTrailEdges:
    def test_consecutive_camps_share_an_edge(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert CAMP_B in graph.adjacency[CAMP_A]
        assert CAMP_A in graph.adjacency[CAMP_B]

    def test_full_linear_chain_connected(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        for id_a, id_b in [(CAMP_A, CAMP_B), (CAMP_B, CAMP_C), (CAMP_C, CAMP_D)]:
            assert id_b in graph.adjacency[id_a], f"missing edge {id_a} → {id_b}"
            assert id_a in graph.adjacency[id_b], f"missing reverse {id_b} → {id_a}"

    def test_edges_are_bidirectional(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        for div_id, neighbors in graph.adjacency.items():
            for neighbor_id in neighbors:
                assert div_id in graph.adjacency[neighbor_id], (
                    f"Edge {div_id}→{neighbor_id} exists but reverse does not"
                )

    def test_non_consecutive_east_bank_camps_have_no_direct_edge(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        assert CAMP_D not in graph.adjacency[CAMP_A]
        assert CAMP_A not in graph.adjacency[CAMP_D]

    def test_camp_a_has_exactly_one_east_bank_neighbor(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        east_bank_camps = {CAMP_A, CAMP_B, CAMP_C, CAMP_D}
        assert east_bank_camps & set(graph.adjacency[CAMP_A]) == {CAMP_B}

    def test_adjacency_lists_are_sorted(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails)
        for div_id, neighbors in graph.adjacency.items():
            assert neighbors == sorted(neighbors), (
                f"adjacency[{div_id}] is not sorted"
            )


# ---------------------------------------------------------------------------
# Genuine trail junction (Nightmare Loop — always valid)
# ---------------------------------------------------------------------------

class TestGenuineJunction:
    """
    Node 9008 is mid-trail on East Bank but the endpoint of Nightmare Loop.
    Because it is not an endpoint of East Bank, this is a genuine junction —
    the CampC/CampD ↔ CampE edge is always included regardless of --trailhead.
    """

    def test_nightmare_reachable_from_east_bank_trailhead_off(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        reachable = any(CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D])
        assert reachable

    def test_nightmare_reachable_from_east_bank_trailhead_on(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=True)
        reachable = any(CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D])
        assert reachable

    def test_junction_camp_degree_at_least_three(self, raw_sites, raw_trails):
        """The East Bank camp nearest node 9008 connects to East Bank neighbors + CampE."""
        graph = build_graph(raw_sites, raw_trails)
        max_degree = max(len(graph.adjacency[c]) for c in [CAMP_C, CAMP_D])
        assert max_degree >= 3


# ---------------------------------------------------------------------------
# Trailhead connection (Copper Ridge — blocked by default)
# ---------------------------------------------------------------------------

class TestTrailheadConnection:
    """
    Node 9001 is the endpoint of BOTH East Bank and Copper Ridge trails.
    CampA ↔ CampF is a trailhead connection — hiker must cross a parking lot.
    """

    def test_trailhead_excluded_by_default(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        assert CAMP_F not in graph.adjacency[CAMP_A]
        assert CAMP_A not in graph.adjacency[CAMP_F]

    def test_trailhead_included_when_flag_set(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=True)
        assert CAMP_F in graph.adjacency[CAMP_A]
        assert CAMP_A in graph.adjacency[CAMP_F]

    def test_trailhead_flag_does_not_affect_within_trail_edges(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        for id_a, id_b in [(CAMP_A, CAMP_B), (CAMP_B, CAMP_C), (CAMP_C, CAMP_D)]:
            assert id_b in graph.adjacency[id_a]

    def test_trailhead_flag_does_not_affect_genuine_junction(self, raw_sites, raw_trails):
        graph = build_graph(raw_sites, raw_trails, allow_trailhead=False)
        reachable = any(CAMP_E in graph.adjacency.get(c, []) for c in [CAMP_C, CAMP_D])
        assert reachable


# ---------------------------------------------------------------------------
# Sites with missing GPS coordinates
# ---------------------------------------------------------------------------

class TestMissingCoordinates:
    def test_site_with_zero_coords_is_isolated(self, raw_trails):
        """A site with lat=0, lon=0 cannot snap to any trail — isolated node."""
        no_gps = [{
            "division_id": "NOGPS001",
            "name": "No GPS Camp",
            "lat": 0,
            "lon": 0,
            "district": "Unknown",
            "children": [],
        }]
        graph = build_graph(no_gps, raw_trails)
        assert graph.adjacency["NOGPS001"] == []

    def test_site_far_from_all_trails_is_isolated(self, raw_trails):
        """A site far outside all trail polylines snaps to nothing."""
        far = [{
            "division_id": "FAR001",
            "name": "Remote Camp",
            "lat": 47.0,
            "lon": -120.0,
            "district": "Unknown",
            "children": [],
        }]
        graph = build_graph(far, raw_trails)
        assert graph.adjacency["FAR001"] == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_trails_produces_isolated_nodes(self, raw_sites):
        graph = build_graph(raw_sites, [])
        assert set(graph.sites.keys()) == {CAMP_A, CAMP_B, CAMP_C, CAMP_D, CAMP_E, CAMP_F}
        for neighbors in graph.adjacency.values():
            assert neighbors == []

    def test_single_site_on_trail_produces_no_edges(self, raw_trails):
        only_one = [{
            "division_id": CAMP_A,
            "name": "Ruby Pasture Camp",
            "lat": 48.72839,
            "lon": -121.01404,
            "district": "East Bank Trail",
            "children": [],
        }]
        graph = build_graph(only_one, raw_trails)
        assert graph.adjacency[CAMP_A] == []

    def test_group_sites_excluded(self, raw_trails):
        group = [{
            "division_id": "G001",
            "name": "Group Site Alpha",
            "lat": 48.72839,
            "lon": -121.01404,
            "district": "East Bank Trail",
            "children": [],
        }]
        graph = build_graph(group, raw_trails)
        assert "G001" not in graph.sites
