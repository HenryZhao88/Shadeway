"""Martins-style bicriteria label-setting over (time, heat).

Keeping the pareto frontier at every node instead of one best label is what
turns the heat-profile slider from a re-route into a display choice.

Label explosion is controlled two ways:
  * epsilon dominance — heat is bucketed to `epsilon_dm` degree-minutes before
    comparison, so near-identical labels collapse
  * a hard cap of `max_labels_per_node`, keeping the time-cheapest labels

The cost function is a callable `(edge_id, enter_at) -> EdgeCost`. This module
imports nothing from thermal/ and knows no physics.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

LAST_STATS: dict[str, float] = {}

DEFAULT_DETOUR_FACTOR = 1.7  # how much longer than the fastest walk we explore
DEFAULT_DETOUR_SLACK_S = 120.0  # ...plus this, so short walks still get options
DEFAULT_MAX_EXTRA_S = 1200.0  # and never more than twenty extra minutes, ever


@dataclass
class Path:
    edges: list[int]
    nodes: list[int]
    enter_times: list[datetime]
    duration_s: float
    heat_dm: float
    mean_feels_like_c: float


@dataclass(order=True)
class _Label:
    arrival_s: float
    heat_dm: float
    node: int = field(compare=False)
    parent: "_Label | None" = field(compare=False, default=None)
    via_edge: int = field(compare=False, default=-1)
    via_duration_s: float = field(compare=False, default=0.0)
    feels_sum: float = field(compare=False, default=0.0)


def _dominates(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """a dominates b when it is no worse on both axes and better on one."""
    return a[0] <= b[0] and a[1] <= b[1] and (a[0] < b[0] or a[1] < b[1])


def time_to_target(
    graph,
    destination: int,
    edge_durations,
    origin: int | None = None,
    detour_factor: float = DEFAULT_DETOUR_FACTOR,
    slack_s: float = DEFAULT_DETOUR_SLACK_S,
    max_extra_s: float = DEFAULT_MAX_EXTRA_S,
) -> tuple:
    """Exact remaining walk time from every node to `destination`, plus a budget.

    Walk time is independent of the time of day, so this whole thing is one
    plain Dijkstra over an array of edge durations — no rays, no weather, no
    sun. It is the piece that makes the bicriteria search affordable: it gives
    both an admissible (in fact exact, so consistent) remaining-time heuristic
    AND the exact fastest duration, from which the exploration budget follows.

    Expansion stops once nothing reachable can still come in under budget, so
    on a fifteen-minute walk this settles a neighbourhood, not a borough.

    Returns (remaining_s, budget_s). remaining_s is inf outside the budget,
    which is exactly the set the forward search must never enter.
    """
    remaining = np.full(graph.n_nodes, np.inf, dtype=np.float64)
    remaining[destination] = 0.0
    budget = np.inf
    queue: list[tuple[float, int]] = [(0.0, int(destination))]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > remaining[node]:
            continue
        if distance > budget:
            break
        if origin is not None and node == origin and budget == np.inf:
            # the fastest walk is now known exactly; everything past this
            # multiple of it is a detour nobody would take for any amount of
            # shade, so it never has to be looked at
            budget = min(
                distance * detour_factor + slack_s, distance + max_extra_s
            )
        for edge_id in graph.neighbours(node):
            edge_id = int(edge_id)
            nxt = graph.other_end(edge_id, node)
            candidate = distance + float(edge_durations[edge_id])
            if candidate < remaining[nxt]:
                remaining[nxt] = candidate
                heapq.heappush(queue, (candidate, nxt))
    remaining[remaining > budget] = np.inf
    return remaining, budget


def search(
    graph,
    origin: int,
    destination: int,
    depart: datetime,
    cost_fn,
    *,
    epsilon_dm: float = 0.1,
    max_labels_per_node: int = 64,
    collect_stats: bool = False,
    remaining_s=None,
    budget_s: float | None = None,
):
    """`remaining_s` / `budget_s` come from `time_to_target` and are optional.

    Without them the search is a plain Martins label-setting run that settles
    the whole reachable graph — correct, but it settles all of Manhattan for a
    ten-block walk. With them, a label is dropped the moment its arrival time
    plus its exact remaining walk time exceeds the budget, which confines the
    search to the corridor between the two points. The heuristic is an exact
    shortest time, so it is consistent and nothing on the frontier inside the
    budget is ever lost.
    """
    if origin >= graph.n_nodes or destination >= graph.n_nodes:
        return []

    horizon_s = float(budget_s) if budget_s is not None else float("inf")

    def over_budget(node: int, arrival_s: float) -> bool:
        if remaining_s is None:
            return arrival_s > horizon_s
        return arrival_s + float(remaining_s[node]) > horizon_s

    start = _Label(arrival_s=0.0, heat_dm=0.0, node=origin)
    queue: list[_Label] = [start]
    frontier: dict[int, list[tuple[float, float]]] = {origin: [(0.0, 0.0)]}
    # bucketed keys kept alongside `frontier`, so the liveness check on pop is
    # a hash lookup instead of rebuilding a set of every label at that node
    live: dict[int, set[tuple[float, int]]] = {origin: {(0.0, 0)}}
    settled_at_destination: list[_Label] = []
    max_labels = 0

    while queue:
        label = heapq.heappop(queue)
        key = (label.arrival_s, round(label.heat_dm / epsilon_dm))
        if key not in live.get(label.node, ()):
            continue  # superseded while queued

        if label.node == destination:
            settled_at_destination.append(label)
            continue

        enter_at = depart + timedelta(seconds=label.arrival_s)
        for edge_id in graph.neighbours(label.node):
            edge_id = int(edge_id)
            nxt = graph.other_end(edge_id, label.node)
            cost = cost_fn(edge_id, enter_at)
            candidate = (
                label.arrival_s + cost.duration_s,
                label.heat_dm + cost.heat_degree_minutes,
            )
            if over_budget(nxt, candidate[0]):
                continue  # cannot reach the destination in time worth walking
            existing = frontier.setdefault(nxt, [])
            keys = live.setdefault(nxt, set())
            bucket = (candidate[0], round(candidate[1] / epsilon_dm) * epsilon_dm)
            if (candidate[0], round(candidate[1] / epsilon_dm)) in keys:
                continue  # exact duplicate (same time, same heat bucket)
            if any(_dominates(
                    (t, round(h / epsilon_dm) * epsilon_dm), bucket)
                   for t, h in existing):
                continue
            existing[:] = [
                (t, h) for t, h in existing
                if not _dominates(bucket, (t, round(h / epsilon_dm) * epsilon_dm))
            ]
            existing.append(candidate)
            if len(existing) > max_labels_per_node:
                existing.sort()
                del existing[max_labels_per_node:]
            keys.clear()
            keys.update((t, round(h / epsilon_dm)) for t, h in existing)
            max_labels = max(max_labels, len(existing))

            heapq.heappush(
                queue,
                _Label(
                    arrival_s=candidate[0],
                    heat_dm=candidate[1],
                    node=nxt,
                    parent=label,
                    via_edge=edge_id,
                    via_duration_s=cost.duration_s,
                    feels_sum=label.feels_sum
                    + cost.mean_feels_like_c * cost.duration_s,
                ),
            )

    if collect_stats:
        LAST_STATS.update(
            {
                "max_labels_at_any_node": max_labels,
                "settled_nodes": len(frontier),
                ("coarse" if epsilon_dm >= 1.0 else "fine"): sum(
                    len(v) for v in frontier.values()
                ),
            }
        )
    return _to_paths(graph, depart, settled_at_destination)


def _to_paths(graph, depart: datetime, labels: list[_Label]) -> list[Path]:
    paths: list[Path] = []
    for label in labels:
        edges: list[int] = []
        durations: list[float] = []
        nodes: list[int] = [label.node]
        cursor = label
        while cursor.parent is not None:
            edges.append(cursor.via_edge)
            durations.append(cursor.via_duration_s)
            nodes.append(cursor.parent.node)
            cursor = cursor.parent
        edges.reverse()
        durations.reverse()
        nodes.reverse()

        # per-edge entry times come from the durations carried on the label
        # chain — this honours the crossing penalty, unlike a fixed-speed guess
        enter_times: list[datetime] = []
        elapsed = 0.0
        for duration_s in durations:
            enter_times.append(depart + timedelta(seconds=elapsed))
            elapsed += duration_s
        paths.append(
            Path(
                edges=edges,
                nodes=nodes,
                enter_times=enter_times,
                duration_s=label.arrival_s,
                heat_dm=label.heat_dm,
                mean_feels_like_c=(
                    label.feels_sum / label.arrival_s if label.arrival_s else 0.0
                ),
            )
        )
    return _prune_dominated(paths)


def _prune_dominated(paths: list[Path]) -> list[Path]:
    ordered = sorted(paths, key=lambda p: (p.duration_s, p.heat_dm))
    kept: list[Path] = []
    best_heat = float("inf")
    for path in ordered:
        if path.heat_dm < best_heat - 1e-9:
            kept.append(path)
            best_heat = path.heat_dm
    return kept


def shortest_time(graph, origin: int, destination: int, depart, cost_fn) -> Path:
    """Plain Dijkstra on time. Used as a sanity check and as the coarse fallback
    when the bicriteria search struggles."""
    paths = search(graph, origin, destination, depart, cost_fn,
                   epsilon_dm=1e9, max_labels_per_node=1)
    return min(paths, key=lambda p: p.duration_s)
