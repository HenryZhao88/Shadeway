from datetime import datetime, timedelta, timezone

import pytest

from shadeway.router import bicriteria
from shadeway.router.graph import Graph
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))
DEPART = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> Graph:
    data = tmp_path_factory.mktemp("bc")
    write_fixture_city(data)
    return Graph.load(data)


def _fake_cost(graph, hot_edges: set[int]):
    """A cost function with no physics in it at all: some edges are simply hot.

    This is the point of the callback design — the router can be tested with a
    made-up cost model and no scene, no weather and no sun.
    """
    from shadeway.cost import EdgeCost

    def traverse(edge_id: int, enter_at):
        duration = float(graph.edge_length_m[edge_id]) / 1.35
        feels = 45.0 if edge_id in hot_edges else 30.0
        return EdgeCost(
            duration_s=duration,
            heat_degree_minutes=feels * duration / 60.0,
            mean_feels_like_c=feels,
            mean_f_sun=1.0 if edge_id in hot_edges else 0.0,
            mean_svf=0.5,
            mean_tmrt_c=feels + 10.0,
        )

    return traverse


def test_returns_at_least_one_path(graph):
    paths = bicriteria.search(graph, 0, 20, DEPART, _fake_cost(graph, set()))
    assert paths
    assert paths[0].edges


def test_frontier_is_strictly_pareto_optimal(graph):
    hot = set(range(0, len(graph.edge_u), 3))
    paths = bicriteria.search(graph, 0, 25, DEPART, _fake_cost(graph, hot))
    ordered = sorted(paths, key=lambda p: p.duration_s)
    for a, b in zip(ordered, ordered[1:]):
        assert b.duration_s > a.duration_s
        assert b.heat_dm < a.heat_dm, "a slower path that is also hotter is dominated"


def test_the_fastest_path_is_also_the_single_objective_optimum(graph):
    paths = bicriteria.search(graph, 0, 25, DEPART, _fake_cost(graph, set()))
    fastest = min(paths, key=lambda p: p.duration_s)
    dijkstra = bicriteria.shortest_time(graph, 0, 25, DEPART, _fake_cost(graph, set()))
    assert abs(fastest.duration_s - dijkstra.duration_s) < 1.0


def test_avoiding_hot_edges_costs_time_but_saves_heat(graph):
    hot = set(range(0, len(graph.edge_u), 2))
    paths = bicriteria.search(graph, 0, 25, DEPART, _fake_cost(graph, hot))
    assert len(paths) >= 2, "a real tradeoff should produce multiple frontier points"
    fastest = min(paths, key=lambda p: p.duration_s)
    coolest = min(paths, key=lambda p: p.heat_dm / max(p.duration_s / 60.0, 1e-6))
    assert coolest.duration_s >= fastest.duration_s
    assert coolest.mean_feels_like_c <= fastest.mean_feels_like_c


def test_epsilon_dominance_reduces_the_label_count(graph):
    hot = set(range(0, len(graph.edge_u), 2))
    bicriteria.search(
        graph, 0, 30, DEPART, _fake_cost(graph, hot), epsilon_dm=5.0, collect_stats=True
    )
    coarse = bicriteria.LAST_STATS["coarse"]
    bicriteria.search(
        graph, 0, 30, DEPART, _fake_cost(graph, hot), epsilon_dm=0.001,
        collect_stats=True,
    )
    fine = bicriteria.LAST_STATS["fine"]
    assert coarse < fine


def test_label_cap_is_respected(graph):
    hot = set(range(0, len(graph.edge_u), 2))
    bicriteria.search(
        graph, 0, 30, DEPART, _fake_cost(graph, hot), max_labels_per_node=4,
        collect_stats=True,
    )
    assert bicriteria.LAST_STATS["max_labels_at_any_node"] <= 4


def test_unreachable_destination_returns_empty_not_an_exception(graph):
    assert bicriteria.search(graph, 0, 10**9, DEPART, _fake_cost(graph, set())) == []


def test_paths_carry_per_edge_entry_times(graph):
    paths = bicriteria.search(graph, 0, 20, DEPART, _fake_cost(graph, set()))
    path = paths[0]
    assert len(path.enter_times) == len(path.edges)
    assert path.enter_times[0] == DEPART
    assert all(b >= a for a, b in zip(path.enter_times, path.enter_times[1:]))
