"""Fixed-point iteration for time-dependent costs.

The problem: an edge's cost depends on when you arrive, and when you arrive
depends on the path so far. The fix: route with the sun at departure, note the
estimated arrival time at every node, re-route using those per-node times,
repeat. It converges in 2-3 passes because the sun moves slowly (about 15
degrees of azimuth per hour) compared to a walk.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from shadeway.router import bicriteria

LAST_ITERATIONS = 0


def solve(graph, origin, destination, depart, cost_model, iterations: int = 3):
    global LAST_ITERATIONS
    cost_model.bind_graph(graph)

    node_arrival_s: dict[int, float] = {}
    paths: list[bicriteria.Path] = []

    for iteration in range(iterations):
        LAST_ITERATIONS = iteration + 1

        def cost_fn(edge_id: int, enter_at: datetime):
            # first pass: enter_at is whatever the search says (departure-based).
            # later passes: refine using the arrival time we learned last round.
            u = int(graph.edge_u[edge_id])
            refined = node_arrival_s.get(u)
            if refined is not None:
                enter_at = depart + timedelta(seconds=refined)
            return cost_model.traverse(edge_id, enter_at)

        paths = bicriteria.search(graph, origin, destination, depart, cost_fn)
        if not paths:
            return []

        previous = dict(node_arrival_s)
        node_arrival_s = {}
        for path in paths:
            for node, enter_at in zip(path.nodes, path.enter_times):
                node_arrival_s.setdefault(node, (enter_at - depart).total_seconds())

        # converged when no node's estimate moved by more than a minute
        if previous and all(
            abs(node_arrival_s.get(n, 0.0) - v) < 60.0 for n, v in previous.items()
        ):
            break

    return paths
