"""The corridor bound: `time_to_target` plus the budget prune in `search`.

The bound is what makes the real cost model affordable — without it the search
settles the whole borough for a ten-block walk. These tests hold it to the only
thing that matters: it must be a pure speedup. Anything on the pareto frontier
that survives the time budget has to come back identical to the unbounded run.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from shadeway.router import bicriteria
from shadeway.router.graph import Graph
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))
DEPART = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> Graph:
    data = tmp_path_factory.mktemp("budget")
    write_fixture_city(data)
    return Graph.load(data)


def _durations(graph, walk_speed_ms: float = 1.35) -> np.ndarray:
    durations = graph.edge_length_m.astype(np.float64) / walk_speed_ms
    return durations + (graph.edge_kind == 1) * 20.0


def _cost(graph, hot: set[int], walk_speed_ms: float = 1.35):
    from shadeway.cost import EdgeCost

    durations = _durations(graph, walk_speed_ms)

    def traverse(edge_id, enter_at):
        seconds = float(durations[edge_id])
        feels = 40.0 if int(edge_id) in hot else 28.0
        return EdgeCost(seconds, feels * seconds / 60.0, feels, 0.9, 0.5, feels + 8.0)

    return traverse


def _ends(graph) -> tuple[int, int]:
    """A short walk along one row of the fixture grid.

    NOT corner to corner: on a uniform grid every node lies on some monotone
    shortest diagonal path, so a diagonal trip has literally nothing outside
    any budget and would test the bound against a case it cannot prune. Two
    stops along a single row leaves the rest of the grid off-corridor, which is
    the situation the bound exists for.
    """
    xy = graph.node_xy
    origin = int(np.argmin(xy[:, 0] + xy[:, 1]))
    row = np.flatnonzero(np.abs(xy[:, 1] - xy[origin, 1]) < 1e-6)
    row = row[np.argsort(xy[row, 0])]
    return origin, int(row[2])


def test_remaining_time_is_zero_at_the_destination_and_finite_nearby(graph):
    origin, destination = _ends(graph)
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin
    )
    assert remaining[destination] == 0.0
    assert np.isfinite(remaining[origin])
    assert budget >= remaining[origin]


def test_budget_is_the_fastest_walk_times_the_detour_factor(graph):
    origin, destination = _ends(graph)
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin,
        detour_factor=1.5, slack_s=0.0, max_extra_s=1e9,
    )
    assert budget == pytest.approx(remaining[origin] * 1.5)


def test_the_absolute_extra_time_cap_binds_on_long_walks(graph):
    origin, destination = _ends(graph)
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin,
        detour_factor=100.0, slack_s=0.0, max_extra_s=60.0,
    )
    assert budget == pytest.approx(remaining[origin] + 60.0)


def test_nodes_outside_the_budget_are_marked_unreachable(graph):
    """Everything the forward search must never enter is marked inf here."""
    origin, destination = _ends(graph)
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin,
        slack_s=0.0,
    )
    assert np.isinf(remaining).any(), "bound never excluded anything to prune"
    assert np.nanmax(remaining[np.isfinite(remaining)]) <= budget + 1e-6


def test_bounded_search_matches_the_unbounded_one_inside_the_budget(graph):
    """The load-bearing test. The bound may drop frontier points that exceed
    the time budget; it may not change any point that does not."""
    origin, destination = _ends(graph)
    hot = {int(i) for i in np.flatnonzero(np.arange(len(graph.edge_u)) % 5 == 0)}
    cost = _cost(graph, hot)

    unbounded = bicriteria.search(graph, origin, destination, DEPART, cost)
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin
    )
    bounded = bicriteria.search(
        graph, origin, destination, DEPART, cost,
        remaining_s=remaining, budget_s=budget,
    )

    expected = [
        (round(p.duration_s, 6), round(p.heat_dm, 6))
        for p in unbounded
        if p.duration_s <= budget + 1e-9
    ]
    actual = [(round(p.duration_s, 6), round(p.heat_dm, 6)) for p in bounded]
    assert actual == expected


def test_the_fastest_path_always_survives_the_bound(graph):
    """Whatever else the bound prunes, it can never prune the answer to
    'just get me there' — that path is by definition inside the budget."""
    origin, destination = _ends(graph)
    cost = _cost(graph, set())
    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin
    )
    bounded = bicriteria.search(
        graph, origin, destination, DEPART, cost,
        remaining_s=remaining, budget_s=budget,
    )
    assert bounded
    assert min(p.duration_s for p in bounded) == pytest.approx(
        remaining[origin], rel=1e-6
    )


def test_the_bound_actually_settles_fewer_nodes(graph):
    """The whole reason the bound exists: on the real graph this is the
    difference between settling a borough and settling a corridor."""
    origin, destination = _ends(graph)
    cost = _cost(graph, set())

    bicriteria.search(graph, origin, destination, DEPART, cost, collect_stats=True)
    unbounded_nodes = bicriteria.LAST_STATS["settled_nodes"]

    remaining, budget = bicriteria.time_to_target(
        graph, destination, _durations(graph), origin=origin
    )
    bicriteria.search(
        graph, origin, destination, DEPART, cost, collect_stats=True,
        remaining_s=remaining, budget_s=budget,
    )
    assert bicriteria.LAST_STATS["settled_nodes"] < unbounded_nodes
