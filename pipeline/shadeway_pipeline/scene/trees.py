"""Census points -> crown circles with a base, a top and a transmissivity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from shadeway_contracts.tables import TREES
from shadeway_pipeline.scene.species import MEDIAN_DBH_CM, lookup

CROWN_BASE_FRACTION = 0.35  # crown starts at 35% of tree height...
CROWN_BASE_MIN_M = 2.0  # ...but never below head height on a street tree


def build_crowns(tree_points) -> pd.DataFrame:
    rows = []
    for i, tree in enumerate(tree_points.itertuples()):
        dbh = float(tree.dbh_cm) if tree.dbh_cm and tree.dbh_cm > 1.0 else MEDIAN_DBH_CM
        measured = bool(tree.dbh_cm and tree.dbh_cm > 1.0)
        tau, tau_source, allometry = lookup(tree.species)
        if not measured:
            tau_source = f"{tau_source}; dbh imputed as median {MEDIAN_DBH_CM}cm"
        top = allometry.height_m(dbh)
        base = max(CROWN_BASE_MIN_M, top * CROWN_BASE_FRACTION)
        rows.append(
            {
                "tree_id": np.uint32(i),
                "x_m": float(tree.geometry.x),
                "y_m": float(tree.geometry.y),
                "species": tree.species or "",
                "dbh_cm": np.float32(dbh),
                "crown_radius_m": np.float32(allometry.crown_radius_m(dbh)),
                "crown_base_m": np.float32(base),
                "crown_top_m": np.float32(max(top, base + 1.0)),
                "tau": np.float32(tau),
                "tau_source": tau_source,
            }
        )
    return pd.DataFrame(rows, columns=TREES.names)
