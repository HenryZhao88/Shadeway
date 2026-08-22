from datetime import datetime, timedelta, timezone

import pytest

from shadeway.router import timedep
from shadeway.router.graph import Graph
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))


class MovingSunCost:
    """A cost model where the hot edges change with time of day — the entire
    reason time dependence exists."""

    def __init__(self, graph):
        self.graph = graph
        self.calls = []

    def bind_graph(self, graph):
        self.graph = graph

    def traverse(self, edge_id, enter_at):
        from shadeway.cost import EdgeCost

        self.calls.append((edge_id, enter_at))
        duration = float(self.graph.edge_length_m[edge_id]) / 1.35
        # before 15:30 the even edges are hot; after, the odd ones
        early = enter_at.hour * 60 + enter_at.minute < 15 * 60 + 30
        hot = (edge_id % 2 == 0) if early else (edge_id % 2 == 1)
        feels = 100.0 if hot else 30.0
        return EdgeCost(duration, feels * duration / 60.0, feels, 1.0, 0.5, feels + 10)


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> Graph:
    data = tmp_path_factory.mktemp("td")
    write_fixture_city(data)
    return Graph.load(data)


def test_converges_and_returns_paths(graph):
    cost = MovingSunCost(graph)
    paths = timedep.solve(graph, 0, 30, datetime(2025, 7, 22, 15, 20, tzinfo=EDT), cost)
    assert paths


def test_later_edges_are_evaluated_at_later_times(graph):
    cost = MovingSunCost(graph)
    depart = datetime(2025, 7, 22, 15, 20, tzinfo=EDT)
    paths = timedep.solve(graph, 0, 30, depart, cost)
    path = paths[0]
    assert path.enter_times[-1] > path.enter_times[0], (
        "if all edges are evaluated at departure time, the sun never moves"
    )


def test_iteration_count_is_bounded(graph):
    cost = MovingSunCost(graph)
    timedep.solve(
        graph, 0, 30, datetime(2025, 7, 22, 15, 20, tzinfo=EDT), cost, iterations=2
    )
    # two full searches, not an unbounded loop
    assert timedep.LAST_ITERATIONS <= 2
