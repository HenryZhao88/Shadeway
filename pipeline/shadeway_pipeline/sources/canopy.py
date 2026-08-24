"""Tree-canopy mask from the 2010 LiDAR land-cover raster, warped to EPSG:32118.

Class 1 of the 7-class scheme is tree canopy (DATA-FINDINGS #11). The raster is
native EPSG:2263 feet; we reproject a scope window to 1 m pixels so the crown
cross-check can compare like with like.
"""

from __future__ import annotations

from shapely.geometry import box

from shadeway_pipeline.config import TARGET_CRS, Scope
from shadeway_pipeline.sources.landcover import _open_raster


def load_window(scope: Scope, resolution_m: float = 1.0):
    """(mask: bool[h, w], transform: Affine) over the scope bbox in TARGET_CRS,
    or None when the raster was never downloaded."""
    dataset = _open_raster()
    if dataset is None:
        return None

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    wgs = gpd_box(scope)
    minx, miny, maxx, maxy = wgs
    width = max(1, int((maxx - minx) / resolution_m))
    height = max(1, int((maxy - miny) / resolution_m))
    dst_transform = from_origin(minx, maxy, resolution_m, resolution_m)

    dst = np.zeros((height, width), dtype=np.uint8)
    reproject(
        source=rasterio.band(dataset, 1),
        destination=dst,
        src_transform=dataset.transform,
        src_crs=dataset.crs,
        dst_transform=dst_transform,
        dst_crs=TARGET_CRS,
        resampling=Resampling.nearest,
    )
    return dst == 1, dst_transform


def gpd_box(scope: Scope) -> tuple[float, float, float, float]:
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    w, s, e, n = scope.bbox_wgs84
    x0, y0 = transformer.transform(w, s)
    x1, y1 = transformer.transform(e, n)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _unused_box_helper():
    # keep the shapely import meaningful for potential polygon clipping later
    return box(0, 0, 1, 1)
