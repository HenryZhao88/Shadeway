"""Synthesise pedestrian crossings at intersections.

The sidewalk dataset does not contain crosswalks, so we invent them. The strategy
is deliberately dumb and therefore robust:

  1. Cluster sidewalk endpoints that sit within CLUSTER_RADIUS_M of each other.
     Each cluster is one real-world intersection corner region.
  2. Inside a cluster, connect every pair of endpoints that belong to DIFFERENT
     parent streets and are no further apart than CROSSING_MAX_SPAN_M.
  3. Refuse anything longer. A 300 m "crossing" is a bug, not a crosswalk.

This over-connects slightly (you get some diagonal corner-cuts that a pedestrian
would actually make anyway) and that is the right failure mode: an extra edge
costs a few milliseconds, a missing edge costs a route.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from shadeway_contracts.tables import EdgeKind, Side
from shadeway_pipeline.config import CROSSING_MAX_SPAN_M

# keep every candidate pair this short (a real crosswalk width), and add longer
# links only when they merge two components — see _select_crossings
ALWAYS_KEEP_SPAN_M = 15.0


def add_crossings(nodes: pd.DataFrame, edges: pd.DataFrame, intersections=None):
    if not len(edges):
        return nodes, edges

    endpoints = _endpoint_frame(nodes, edges)
    coords = endpoints[["x_m", "y_m"]].to_numpy()

    # all candidate endpoint pairs within the max span, via KD-tree. A plain
    # all-pairs scan is O(n^2); at Manhattan scale that is minutes vs seconds.
    tree = cKDTree(coords)
    pairs = tree.query_pairs(CROSSING_MAX_SPAN_M, output_type="ndarray")

    a_pts = coords[pairs[:, 0]]
    b_pts = coords[pairs[:, 1]]
    spans = np.hypot(a_pts[:, 0] - b_pts[:, 0], a_pts[:, 1] - b_pts[:, 1])

    phys = endpoints["physical_id"].to_numpy()
    node_ids = endpoints["node_id"].to_numpy()
    street_names = endpoints["street_name"].to_numpy()

    candidates: list[tuple[float, int, int]] = []
    for k, (i, j) in enumerate(pairs):
        span = float(spans[k])
        if span <= 0.0:
            continue
        if phys[i] == phys[j]:
            continue  # same street's two sides or continuation: not a crossing
        if node_ids[i] == node_ids[j]:
            continue
        candidates.append((span, int(i), int(j)))

    chosen = _select_crossings(candidates)

    rows: list[dict] = []
    for span, i, j in chosen:
        a, b = endpoints.iloc[i], endpoints.iloc[j]
        rows.append(
            {
                "u": int(a.node_id),
                "v": int(b.node_id),
                "kind": int(EdgeKind.CROSSING),
                "side": int(Side.NONE),
                "street_name": f"{a.street_name} / {b.street_name}",
                "physical_id": -1,
                "bearing_deg": float(
                    (np.degrees(np.arctan2(b.x_m - a.x_m, b.y_m - a.y_m)) + 360.0)
                    % 360.0
                ),
                "length_m": span,
                "width_m": None,
                "geometry": LineString([(a.x_m, a.y_m), (b.x_m, b.y_m)]),
            }
        )

    if not rows:
        return nodes, edges

    added = pd.DataFrame(rows)
    combined = pd.concat([edges.drop(columns=["edge_id"]), added], ignore_index=True)
    combined.insert(0, "edge_id", np.arange(len(combined), dtype=np.uint32))
    return nodes, combined


def _select_crossings(
    candidates: list[tuple[float, int, int]]
) -> list[tuple[float, int, int]]:
    """Choose crossings so connectivity is preserved without bloat.

    Short spans are kept unconditionally — those are real crosswalks. Longer
    ones are added shortest-first, but only when they actually merge two
    components of the crossing graph. This keeps ~one link per junction instead
    of the complete pairwise graph, while provably reaching every component the
    candidate set can reach.
    """
    parent: dict[int, int] = {}

    def find(a: int) -> int:
        while parent.get(a, a) != a:
            parent[a] = parent.get(parent[a], parent[a])
            a = parent[a]
        return a

    chosen: list[tuple[float, int, int]] = []
    for span, i, j in sorted(candidates):
        if span <= ALWAYS_KEEP_SPAN_M:
            chosen.append((span, i, j))
            ru, rv = find(i), find(j)
            if ru != rv:
                parent[ru] = rv
            continue
        ru, rv = find(i), find(j)
        if ru != rv:
            parent[ru] = rv
            chosen.append((span, i, j))
    return chosen


def _endpoint_frame(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    lookup = nodes.set_index("node_id")[["x_m", "y_m"]]
    frames = []
    for column in ("u", "v"):
        part = edges[[column, "street_name", "physical_id"]].rename(
            columns={column: "node_id"}
        )
        part = part.join(lookup, on="node_id")
        frames.append(part)
    return pd.concat(frames, ignore_index=True).dropna(subset=["x_m", "y_m"])


def connectivity_report(nodes: pd.DataFrame, edges: pd.DataFrame) -> dict:
    """Union-find over the edge list. This is the number you check every time you
    rebuild — a drop in largest_component_fraction means you broke something."""
    parent = {int(n): int(n) for n in nodes["node_id"]}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for u, v in zip(edges["u"], edges["v"]):
        ru, rv = find(int(u)), find(int(v))
        if ru != rv:
            parent[ru] = rv

    sizes: dict[int, int] = {}
    for n in parent:
        sizes[find(n)] = sizes.get(find(n), 0) + 1
    touched = set(edges["u"]) | set(edges["v"])
    return {
        "n_components": len(sizes),
        "largest_component_fraction": (max(sizes.values()) / len(parent)) if parent else 0.0,
        "orphan_nodes": int(len(set(parent) - touched)),
    }
