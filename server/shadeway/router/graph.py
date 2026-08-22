"""The graph as flat numpy arrays with CSR adjacency.

Pedestrian edges are undirected: every edge appears in both endpoints'
neighbour lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely

from shadeway_contracts.tables import read_table


@dataclass
class Graph:
    n_nodes: int
    n_samples: int
    node_xy: np.ndarray  # (n, 2) float64, EPSG:32118
    node_lonlat: np.ndarray  # (n, 2) float64, WGS84
    edge_u: np.ndarray
    edge_v: np.ndarray
    edge_kind: np.ndarray
    edge_side: np.ndarray
    edge_length_m: np.ndarray
    edge_bearing_deg: np.ndarray
    sample_start: np.ndarray
    sample_count: np.ndarray
    street_names: list[str]
    geoms: list[object]
    sample_xy: np.ndarray  # (n_samples, 2)
    sample_albedo: np.ndarray
    adj_offsets: np.ndarray
    adj_edges: np.ndarray

    @classmethod
    def load(cls, data_dir: Path) -> "Graph":
        data_dir = Path(data_dir)
        nodes = read_table(data_dir / "nodes.parquet")
        edges = read_table(data_dir / "edges.parquet")
        samples = read_table(data_dir / "samples.parquet")

        node_xy = np.column_stack(
            [np.asarray(nodes.column("x_m")), np.asarray(nodes.column("y_m"))]
        )
        node_lonlat = np.column_stack(
            [np.asarray(nodes.column("lon")), np.asarray(nodes.column("lat"))]
        )
        u = np.asarray(edges.column("u"), dtype=np.int64)
        v = np.asarray(edges.column("v"), dtype=np.int64)

        # CSR adjacency over an undirected edge list
        n_nodes = len(node_xy)
        degree = np.bincount(np.concatenate([u, v]), minlength=n_nodes)
        offsets = np.zeros(n_nodes + 1, dtype=np.int64)
        np.cumsum(degree, out=offsets[1:])
        cursor = offsets[:-1].copy()
        adj = np.zeros(offsets[-1], dtype=np.int64)
        for edge_id, (a, b) in enumerate(zip(u, v)):
            adj[cursor[a]] = edge_id
            cursor[a] += 1
            adj[cursor[b]] = edge_id
            cursor[b] += 1

        return cls(
            n_nodes=n_nodes,
            n_samples=samples.num_rows,
            node_xy=node_xy,
            node_lonlat=node_lonlat,
            edge_u=u,
            edge_v=v,
            edge_kind=np.asarray(edges.column("kind"), dtype=np.uint8),
            edge_side=np.asarray(edges.column("side"), dtype=np.int8),
            edge_length_m=np.asarray(edges.column("length_m"), dtype=np.float32),
            edge_bearing_deg=np.asarray(edges.column("bearing_deg"), dtype=np.float32),
            sample_start=np.asarray(edges.column("sample_start"), dtype=np.int64),
            sample_count=np.asarray(edges.column("sample_count"), dtype=np.int64),
            street_names=edges.column("street_name").to_pylist(),
            geoms=list(shapely.from_wkb(edges.column("geom_wkb").to_pylist())),
            sample_xy=np.column_stack(
                [np.asarray(samples.column("x_m")), np.asarray(samples.column("y_m"))]
            ),
            sample_albedo=np.asarray(samples.column("ground_albedo"), dtype=np.float32),
            adj_offsets=offsets,
            adj_edges=adj,
        )

    def neighbours(self, node_id: int) -> np.ndarray:
        return self.adj_edges[self.adj_offsets[node_id] : self.adj_offsets[node_id + 1]]

    def other_end(self, edge_id: int, node_id: int) -> int:
        u = int(self.edge_u[edge_id])
        return int(self.edge_v[edge_id]) if u == node_id else u

    def nearest_node(self, lon: float, lat: float) -> int:
        d = np.hypot(
            self.node_lonlat[:, 0] - lon, self.node_lonlat[:, 1] - lat
        )
        return int(np.argmin(d))

    def sample_ids(self, edge_id: int) -> np.ndarray:
        start = int(self.sample_start[edge_id])
        return np.arange(start, start + int(self.sample_count[edge_id]), dtype=np.int64)
