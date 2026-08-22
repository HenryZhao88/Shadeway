"""THE SPIKE. Run this before building anything that depends on hosting.

The whole free-deployment plan rests on the bicriteria search being fast in pure
Python. Measure it, write the number down, tell the team.
"""

import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DATA = Path(os.environ.get("SHADEWAY_DATA", "data/nyc"))
pytestmark = pytest.mark.skipif(
    not (DATA / "edges.parquet").exists(),
    reason="needs a built city — run `make data SCOPE=manhattan`",
)

EDT = timezone(timedelta(hours=-4))
DEPART = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)


def _flat_cost(graph):
    """Constant cost. We are timing the SEARCH, not the physics."""
    from shadeway.cost import EdgeCost

    def traverse(edge_id, enter_at):
        seconds = float(graph.edge_length_m[edge_id]) / 1.35
        return EdgeCost(seconds, 35.0 * seconds / 60.0, 35.0, 0.5, 0.5, 45.0)

    return traverse


def test_report_router_latency():
    from shadeway.router import bicriteria
    from shadeway.router.graph import Graph

    graph = Graph.load(DATA)
    cost = _flat_cost(graph)

    # Bryant Park -> Grand Central, then a longer cross-town leg
    pairs = [
        ((-73.9840, 40.7536), (-73.9772, 40.7527)),
        ((-73.9855, 40.7580), (-73.9857, 40.7484)),
        ((-74.0060, 40.7128), (-73.9680, 40.7850)),  # deliberately long
    ]

    print(f"\n  graph: {len(graph.edge_u):,} edges, {graph.n_nodes:,} nodes")
    all_times = []
    for origin_ll, dest_ll in pairs:
        origin = graph.nearest_node(*origin_ll)
        destination = graph.nearest_node(*dest_ll)
        bicriteria.search(graph, origin, destination, DEPART, cost)  # warm imports

        runs = []
        for _ in range(5):
            started = time.perf_counter()
            paths = bicriteria.search(graph, origin, destination, DEPART, cost)
            runs.append(time.perf_counter() - started)
        all_times.extend(runs)
        print(
            f"  {origin:>6} -> {destination:<6} "
            f"p50 {statistics.median(runs)*1000:7.0f} ms   "
            f"max {max(runs)*1000:7.0f} ms   {len(paths)} frontier points"
        )

    p50 = statistics.median(all_times) * 1000
    worst = max(all_times) * 1000
    print(f"\n  OVERALL p50 {p50:.0f} ms   worst {worst:.0f} ms")
    print("  < 1000 ms  -> Vercel plan CONFIRMED")
    print("  1-3 s      -> tune epsilon_dm / max_labels_per_node, re-measure")
    print("  > 5 s      -> take the lambda-sweep fallback, or move to Oracle")

    assert worst < 10_000, (
        f"router is {worst:.0f} ms — unusable at any hosting choice. "
        "Take the single-objective lambda-sweep fallback (design doc, router section)."
    )
