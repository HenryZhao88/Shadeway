"""The occluder scene: prisms and crowns, indexed for 2D ray queries.

Loaded once at startup, then read-only except through scene_edit.py (Task 13),
which bumps `version` and invalidates the affected horizon cache entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    tree_species: list[str] = field(default_factory=list)  # spc_latin per crown
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
            # carried so instructions can say "honey locusts, so dappled light,
            # not real shade" rather than the anonymous "tree canopy"
            tree_species=trees.column("species").to_pylist(),
        )

    def buildings_near(self, x: float, y: float, radius_m: float) -> np.ndarray:
        return self.building_tree.query(
            shapely.buffer(shapely.points(x, y), radius_m)
        )

    def plant_crowns(
        self,
        xy: np.ndarray,
        crown_radius_m: np.ndarray,
        crown_base_m: np.ndarray,
        crown_top_m: np.ndarray,
        tau: np.ndarray,
        species: str = "",
    ) -> None:
        """Append planted crowns and bump `version`. The lazy kd-tree over
        trunk positions is reset so the next shade query sees the newcomers;
        callers must invalidate affected HorizonCache entries themselves."""
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        if not len(xy):
            return
        self.tree_xy = np.concatenate([self.tree_xy, xy])
        self.tree_radius_m = np.concatenate(
            [self.tree_radius_m, np.asarray(crown_radius_m, dtype=np.float32)]
        )
        self.crown_base_m = np.concatenate(
            [self.crown_base_m, np.asarray(crown_base_m, dtype=np.float32)]
        )
        self.crown_top_m = np.concatenate(
            [self.crown_top_m, np.asarray(crown_top_m, dtype=np.float32)]
        )
        self.tau = np.concatenate([self.tau, np.asarray(tau, dtype=np.float32)])
        # keep species aligned with tree_xy — evidence lookups index by crown
        self.tree_species.extend([species] * len(xy))
        self._kdtree = None  # noqa: SLF001 — rebuilt lazily by occluder
        self.version += 1
