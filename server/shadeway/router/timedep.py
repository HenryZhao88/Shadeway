"""Time-dependent routing: why there is no fixed-point loop here any more.

The design doc planned a fixed-point iteration because it assumed the search
would freeze the sun at the departure time. The implemented search never does:
`bicriteria.search` hands every cost callback the arriving label's true arrival
time (`depart + label.arrival_s`). And since walk durations do not depend on
time of day (constant speed plus a constant crossing penalty), a path's arrival
times are fully determined by its edge sequence — there is nothing left for a
fixed point to converge. Heat is therefore evaluated exactly, at the moment you
actually step onto each edge, in ONE search.
"""

from __future__ import annotations

from shadeway.router import bicriteria

LAST_ITERATIONS = 0


def solve(graph, origin, destination, depart, cost_model, *, detour_factor=None, **_):
    """Return the pareto frontier of (time, heat) paths, time-exactly.

    The one preliminary step is a physics-free time Dijkstra from the
    destination (`bicriteria.time_to_target`). It costs milliseconds, needs no
    weather and no sun, and it hands the real search an exact remaining-time
    bound — without which the search settles every node in the borough before
    it will admit that a walk to the next block is finished.
    """
    global LAST_ITERATIONS
    cost_model.bind_graph(graph)
    durations = getattr(cost_model, "edge_durations", None)
    if durations is None:
        # a cost model that cannot state its walk times up front (test doubles,
        # anything experimental) still routes — just without the bound
        remaining, budget = None, None
    else:
        remaining, budget = bicriteria.time_to_target(
            graph,
            destination,
            durations(),
            origin=origin,
            **({} if detour_factor is None else {"detour_factor": detour_factor}),
        )
    paths = bicriteria.search(
        graph,
        origin,
        destination,
        depart,
        cost_model.traverse,
        remaining_s=remaining,
        budget_s=budget,
    )
    LAST_ITERATIONS = 1
    return paths
