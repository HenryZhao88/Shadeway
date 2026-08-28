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

import numpy as np

from shadeway.router import bicriteria

LAST_ITERATIONS = 0
MAX_PREFETCH_KEYS = 100_000
ROUTER_REVISION = "batched-corridor-v1"


def _prefetch_corridor(
    graph, origin, destination, depart, cost_model, durations, remaining, budget,
    *, detour_factor=None,
) -> None:
    """Batch the exact edge/minute keys that can fit inside the time corridor."""
    prefetch = getattr(cost_model, "prefetch", None)
    if prefetch is None or not np.isfinite(budget):
        return
    kwargs = {} if detour_factor is None else {"detour_factor": detour_factor}
    from_origin, _ = bicriteria.time_to_target(
        graph, origin, durations, origin=destination, **kwargs
    )
    edge_u = graph.edge_u
    edge_v = graph.edge_v
    feasible_uv = (
        np.isfinite(from_origin[edge_u])
        & np.isfinite(remaining[edge_v])
        & (from_origin[edge_u] + durations + remaining[edge_v] <= budget + 1e-9)
    )
    feasible_vu = (
        np.isfinite(from_origin[edge_v])
        & np.isfinite(remaining[edge_u])
        & (from_origin[edge_v] + durations + remaining[edge_u] <= budget + 1e-9)
    )
    earliest = np.minimum(
        np.where(feasible_uv, from_origin[edge_u], np.inf),
        np.where(feasible_vu, from_origin[edge_v], np.inf),
    )
    latest = np.maximum(
        np.where(feasible_uv, budget - durations - remaining[edge_v], -np.inf),
        np.where(feasible_vu, budget - durations - remaining[edge_u], -np.inf),
    )
    valid = np.isfinite(earliest) & np.isfinite(latest) & (earliest <= latest)
    edge_ids = np.flatnonzero(valid)
    if not len(edge_ids):
        return

    depart_s = depart.timestamp()
    low = np.floor((depart_s + earliest[valid]) / 60.0).astype(np.int64)
    high = np.floor((depart_s + latest[valid]) / 60.0).astype(np.int64)
    counts = high - low + 1
    total = int(counts.sum())
    if total > MAX_PREFETCH_KEYS:
        return
    offsets = np.cumsum(counts) - counts
    repeated_offsets = np.repeat(offsets, counts)
    minutes = (
        np.repeat(low, counts)
        + np.arange(total, dtype=np.int64)
        - repeated_offsets
    )
    prefetch(np.repeat(edge_ids, counts), minutes)


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
    durations_fn = getattr(cost_model, "edge_durations", None)
    if durations_fn is None:
        # a cost model that cannot state its walk times up front (test doubles,
        # anything experimental) still routes — just without the bound
        durations, remaining, budget = None, None, None
    else:
        durations = durations_fn()
        remaining, budget = bicriteria.time_to_target(
            graph,
            destination,
            durations,
            origin=origin,
            **({} if detour_factor is None else {"detour_factor": detour_factor}),
        )
        _prefetch_corridor(
            graph,
            origin,
            destination,
            depart,
            cost_model,
            durations,
            remaining,
            budget,
            detour_factor=detour_factor,
        )
    paths = bicriteria.search(
        graph,
        origin,
        destination,
        depart,
        cost_model.traverse,
        remaining_s=remaining,
        budget_s=budget,
        edge_durations=durations,
    )
    LAST_ITERATIONS = 1
    return paths
