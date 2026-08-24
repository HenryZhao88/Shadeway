"""Building footprints with height, derived from LiDAR. These are our occluders.

Each footprint becomes a vertical prism: the polygon extruded from `base_m` to
`base_m + height_m`. That is the entire building model, and it is enough, because
the shade test is 2D.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from shadeway_pipeline.config import CACHE_DIR, FEET_TO_M, TARGET_CRS, Scope
from shadeway_pipeline.sources.fetch import socrata_geojson
from shadeway_pipeline.sources.resolve import load_datasets

FEET_TO_M_LOCAL = FEET_TO_M
MIN_HEIGHT_M = 2.0  # below this it casts no shade worth modelling

# feature_code 2100 = buildings, 5110 = low structures (garages, sheds — they shade).
# Everything else is skybridges, misc — drop. See DATA-FINDINGS #5.
KEEP_FEATURE_CODES = {"2100", "5110"}

# fetch_nyc.sh cached one file per borough under these names
PREFETCHED = {
    "1": CACHE_DIR / "buildings_manhattan.geojson",
    "3": CACHE_DIR / "buildings_brooklyn.geojson",
}


# BIN prefix per borough code. A BIN is a 7-digit number whose leading digit is
# the borough, so the range [n000000, n999999] is that borough's buildings.
BIN_PREFIX = {"1": 1_000_000, "2": 2_000_000, "3": 3_000_000,
              "4": 4_000_000, "5": 5_000_000}


def _download(scope: Scope) -> list[Path]:
    """One source per borough in the scope, prefetched or downloaded.

    Resolved PER BOROUGH rather than all-or-nothing. The earlier version bailed
    out to a single download keyed on `scope.boroughs[0]` the moment any
    prefetch file was missing, which silently built manhattan+brooklyn with
    Manhattan's buildings only — a scene with half its occluders in it and no
    error to say so. It also returned a partial prefetch list without
    downloading the rest.
    """
    paths: list[Path] = []
    for borough in scope.boroughs:
        cached = PREFETCHED.get(borough)
        if cached is not None and cached.exists():
            paths.append(cached)
            continue
        bin_lo = BIN_PREFIX.get(borough)
        if bin_lo is None:
            raise ValueError(
                f"no BIN range known for borough code {borough!r}; "
                "add it to BIN_PREFIX before building this scope"
            )
        where = (
            f"bin >= {bin_lo} AND bin < {bin_lo + 1_000_000} "
            f"AND feature_code IN ('2100','5110')"
        )
        paths.append(socrata_geojson(load_datasets()["buildings"], where=where))
    return paths


def _scope_bounds(scope: Scope):
    bbox = gpd.GeoSeries([box(*scope.bbox_wgs84)], crs="EPSG:4326").to_crs(TARGET_CRS)
    minx, miny, maxx, maxy = bbox.total_bounds
    return minx, miny, maxx, maxy


def load(scope: Scope) -> gpd.GeoDataFrame:
    frames = []
    for path in _download(scope):
        part = gpd.read_file(path)
        if "feature_code" in part.columns:
            part = part[part["feature_code"].astype(str).isin(KEEP_FEATURE_CODES)]
        frames.append(part)
    frame = pd.concat(frames, ignore_index=True)
    frame = gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs or "EPSG:4326")
    frame = frame.to_crs(TARGET_CRS)
    frame = frame.cx[_scope_bounds(scope)[0]:_scope_bounds(scope)[2],
                     _scope_bounds(scope)[1]:_scope_bounds(scope)[3]]
    frame = frame.explode(index_parts=False)

    height_m = pd.to_numeric(frame["height_roof"], errors="coerce") * FEET_TO_M_LOCAL
    if "ground_elevation" in frame.columns:
        base_m = pd.to_numeric(frame["ground_elevation"], errors="coerce").fillna(0.0)
    else:
        base_m = pd.Series(0.0, index=frame.index)
    base_m = base_m * FEET_TO_M_LOCAL

    out = gpd.GeoDataFrame(
        {
            "height_m": height_m.values,
            "base_m": base_m.values,
            "geometry": frame.geometry.values,
        },
        crs=TARGET_CRS,
    )
    out = out[out.geometry.notna() & out.geometry.is_valid]
    out = out[out["height_m"] >= MIN_HEIGHT_M]
    out.insert(0, "building_id", range(len(out)))
    return out.reset_index(drop=True)
