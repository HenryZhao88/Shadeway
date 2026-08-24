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


def solve(graph, origin, destination, depart, cost_model, **_):
    """Return the pareto frontier of (time, heat) paths, time-exactly."""
    global LAST_ITERATIONS
    cost_model.bind_graph(graph)
    paths = bicriteria.search(graph, origin, destination, depart, cost_model.traverse)
    LAST_ITERATIONS = 1
    return paths
