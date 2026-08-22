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

LAST_STATS: dict[str, float] = {}


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
):
    if origin >= graph.n_nodes or destination >= graph.n_nodes:
        return []

    start = _Label(arrival_s=0.0, heat_dm=0.0, node=origin)
    queue: list[_Label] = [start]
    frontier: dict[int, list[tuple[float, float]]] = {origin: [(0.0, 0.0)]}
    settled_at_destination: list[_Label] = []
    max_labels = 0

    while queue:
        label = heapq.heappop(queue)
        key = (label.arrival_s, round(label.heat_dm / epsilon_dm))
        if key not in {
            (t, round(h / epsilon_dm)) for t, h in frontier.get(label.node, [])
        }:
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
            bucket = (candidate[0], round(candidate[1] / epsilon_dm) * epsilon_dm)

            existing = frontier.setdefault(nxt, [])
            if any(_dominates((t, round(h / epsilon_dm) * epsilon_dm), bucket)
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
