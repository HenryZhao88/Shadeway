"""Lay down evaluation points along every edge, ~10 m apart.

The horizon cache is a dense uint8[2][n_samples][72] array indexed directly by
sample_id. That only works if each edge's samples are contiguous and ordered
from u to v. Both properties are asserted by the tests; do not break them for
convenience.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from shadeway_contracts.tables import SAMPLE_SPACING_M
from shadeway_pipeline.sources import landcover


def add_samples(edges: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    starts = np.zeros(len(edges), dtype=np.uint32)
    counts = np.zeros(len(edges), dtype=np.uint16)
    ts: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    edge_ids: list[int] = []

    cursor = 0
    for i, row in enumerate(edges.itertuples()):
        geom = row.geometry
        n = max(2, int(np.ceil(geom.length / SAMPLE_SPACING_M)) + 1)
        fractions = np.linspace(0.0, 1.0, n)
        starts[i] = cursor
        counts[i] = n
        cursor += n
        ts.extend(float(t) for t in fractions)
        for t in fractions:
            p = geom.interpolate(float(t), normalized=True)
            xs.append(p.x)
            ys.append(p.y)
        edge_ids.extend([int(row.edge_id)] * n)

    xs_arr = np.asarray(xs, dtype=np.float64)
    ys_arr = np.asarray(ys, dtype=np.float64)
    albedo, classes = landcover.albedo_at(xs_arr, ys_arr)

    samples = pd.DataFrame(
        {
            "sample_id": np.arange(cursor, dtype=np.uint32),
            "edge_id": np.asarray(edge_ids, dtype=np.uint32),
            "t": np.asarray(ts, dtype=np.float32),
            "x_m": xs_arr,
            "y_m": ys_arr,
            "ground_albedo": albedo.astype(np.float32),
            "landcover_class": classes.astype(np.uint8),
        }
    )
    out = edges.copy()
    out["sample_start"] = starts
    out["sample_count"] = counts
    return out, samples
