"""The occluder scene: prisms and crowns, indexed for 2D ray queries.

Loaded once at startup, then read-only except through scene_edit.py (Task 13),
which bumps `version` and invalidates the affected horizon cache entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import Polygon

from shadeway_contracts.tables import read_table


@dataclass
class Scene:
    building_geoms: list[Polygon]
    building_heights_m: np.ndarray  # float32, metres above base
    building_bases_m: np.ndarray  # float32
    building_tree: STRtree
    tree_xy: np.ndarray  # float64 (n, 2)
    tree_radius_m: np.ndarray  # float32
    crown_base_m: np.ndarray  # float32
    crown_top_m: np.ndarray  # float32
    tau: np.ndarray  # float32
    tree_tree: STRtree
    version: int = 1

    @classmethod
    def load(cls, data_dir: Path) -> "Scene":
        data_dir = Path(data_dir)
        buildings = read_table(data_dir / "buildings.parquet")
        trees = read_table(data_dir / "trees.parquet")

        geoms = shapely.from_wkb(buildings.column("geom_wkb").to_pylist())
        heights = np.asarray(buildings.column("height_m"), dtype=np.float32)
        bases = np.asarray(buildings.column("base_m"), dtype=np.float32)

        xy = np.column_stack(
            [
                np.asarray(trees.column("x_m"), dtype=np.float64),
                np.asarray(trees.column("y_m"), dtype=np.float64),
            ]
        )
        radius = np.asarray(trees.column("crown_radius_m"), dtype=np.float32)
        crown_points = shapely.points(xy[:, 0], xy[:, 1]) if len(xy) else []

        return cls(
            building_geoms=list(geoms),
            building_heights_m=heights,
            building_bases_m=bases,
            building_tree=STRtree(list(geoms)),
            tree_xy=xy,
            tree_radius_m=radius,
            crown_base_m=np.asarray(trees.column("crown_base_m"), dtype=np.float32),
            crown_top_m=np.asarray(trees.column("crown_top_m"), dtype=np.float32),
            tau=np.asarray(trees.column("tau"), dtype=np.float32),
            tree_tree=STRtree(list(crown_points)),
        )

    def buildings_near(self, x: float, y: float, radius_m: float) -> np.ndarray:
        return self.building_tree.query(
            shapely.buffer(shapely.points(x, y), radius_m)
        )
