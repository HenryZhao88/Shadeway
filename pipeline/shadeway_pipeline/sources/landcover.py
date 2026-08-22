"""LiDAR land cover -> ground albedo per sample point.

We need ground albedo for the reflected-shortwave term in the thermal model.
Every class value below carries a citation (see the table for sources).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from pyproj import Transformer

from shadeway_pipeline.config import CACHE_DIR

# NYC 2010 3ft land cover classes (VERIFIED from the value attribute table):
# 1 tree canopy, 2 grass/shrub, 3 bare earth, 4 water,
# 5 buildings, 6 roads, 7 other paved
# (the 2017 6-inch vintage adds an 8th class, railroads — we use 2010, see
#  DATA-FINDINGS #11 for why)
#
# Albedo sources (read 2026-08-22):
#  * SUEWS "Typical Values" table (docs.suews.io), compiling Oke (1987/2002):
#    paved 0.12 · buildings 0.15 · bare soil 0.21 · evergreen 0.10 ·
#    deciduous trees 0.18 · grass 0.21 · water 0.10
#  * NREL "Ground Albedo Measurements and Modeling" (Marion, NREL/TP-72589,
#    2020): asphalt pavement 0.09-0.18 · concrete pavement 0.20-0.40 ·
#    grass 0.15-0.26
CLASS_ALBEDO: dict[int, float] = {
    1: 0.18,  # tree canopy   # source: Oke DecTr 0.18 via SUEWS Typical Values
    2: 0.21,  # grass / shrub # source: Oke grass 0.21 via SUEWS; NREL 0.15-0.26
    3: 0.20,  # bare soil     # source: Oke bare soil 0.19-0.21 via SUEWS
    4: 0.07,  # water         # source: Oke water 0.10; 0.07 = fresh-water low end
    5: 0.15,  # building roof # source: Oke buildings 0.15 via SUEWS
    6: 0.12,  # road (asphalt)# source: Oke paved 0.12; NREL asphalt 0.09-0.18
    7: 0.25,  # concrete sidewalk # source: NREL concrete 0.20-0.40, mid-low end
}
DEFAULT_CLASS = 7  # concrete sidewalk: what a pedestrian is usually standing on
DEFAULT_ALBEDO = CLASS_ALBEDO[DEFAULT_CLASS]

RASTER_PATH = CACHE_DIR / "landcover_2010_nyc_3ft.img"  # ERDAS HFA; rasterio reads it natively


@lru_cache(maxsize=1)
def _open_raster():
    """Return an open rasterio dataset, or None if we never got the raster.

    Already downloaded (115 MB, data/cache/). If it is missing we degrade to
    DEFAULT_ALBEDO everywhere and say so in validate.py.
    That is an acceptable, documented loss of fidelity — it is NOT acceptable to
    silently pretend we have it.
    """
    if not RASTER_PATH.exists():
        return None
    import rasterio

    return rasterio.open(RASTER_PATH)


@lru_cache(maxsize=1)
def _to_raster_crs() -> Transformer | None:
    dataset = _open_raster()
    if dataset is None:
        return None
    # VERIFIED live: the raster opens as EPSG:2263 (state plane FEET) — see
    # DATA-FINDINGS #11. Our sample points arrive in EPSG:32118 metres.
    return Transformer.from_crs("EPSG:32118", dataset.crs, always_xy=True)


def albedo_at(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Ground albedo and land-cover class at projected points (EPSG:32118)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    dataset = _open_raster()
    if dataset is None:
        n = len(xs)
        return (
            np.full(n, DEFAULT_ALBEDO, dtype=np.float32),
            np.full(n, DEFAULT_CLASS, dtype=np.uint8),
        )
    transformer = _to_raster_crs()
    rx, ry = transformer.transform(xs, ys)
    classes = np.fromiter(
        (v[0] for v in dataset.sample(zip(rx, ry))), dtype=np.uint8, count=len(xs)
    )
    albedo = np.array(
        [CLASS_ALBEDO.get(int(c), DEFAULT_ALBEDO) for c in classes], dtype=np.float32
    )
    return albedo, classes
