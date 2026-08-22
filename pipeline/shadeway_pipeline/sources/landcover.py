"""LiDAR land cover -> ground albedo per sample point.

We need ground albedo for the reflected-shortwave term in the thermal model.
Asphalt reflects almost nothing; concrete reflects a fair amount; grass is in
between. Getting this wrong shifts felt temperature by a degree or two, which
matters but is not catastrophic — hence the documented fallback.

ALBEDO VALUES BELOW ARE PLACEHOLDERS UNTIL SOURCED.
Replace each with a literature value and a `# source:` comment before the demo.
Good sources: Oke, *Boundary Layer Climates* (2nd ed.) Table 1.1 for surface
albedos; the SOLWEIG/UMEP land-cover defaults in UMEP-dev/UMEP.
Record whatever you use in docs/model.md.
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
CLASS_ALBEDO: dict[int, float] = {
    1: 0.15,  # tree canopy      # source: PLACEHOLDER
    2: 0.22,  # grass / shrub    # source: PLACEHOLDER
    3: 0.18,  # bare soil        # source: PLACEHOLDER
    4: 0.07,  # water            # source: PLACEHOLDER
    5: 0.20,  # building roof    # source: PLACEHOLDER
    6: 0.10,  # road (asphalt)   # source: PLACEHOLDER
    7: 0.25,  # other impervious (concrete sidewalk)  # source: PLACEHOLDER
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
