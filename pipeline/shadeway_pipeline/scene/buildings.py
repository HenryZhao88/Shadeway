"""Footprints -> vertical prisms. This is the whole building model.

There is no roof shape, no setback, no facade detail, and we do not need any:
the shade test is a 2D ray against a plan-view polygon with a height. A prism is
exactly the information that test consumes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_prisms(footprints) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "building_id": np.arange(len(footprints), dtype=np.uint32),
            "height_m": footprints["height_m"].to_numpy(np.float32),
            "base_m": footprints["base_m"].to_numpy(np.float32),
            "geom_wkb": [g.wkb for g in footprints.geometry],
        }
    )
