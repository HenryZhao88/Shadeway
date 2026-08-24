"""NYC Street Centerline. This is the routable skeleton — real topology, properly
connected. Everything in the graph descends from this."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from shadeway_pipeline.config import (
    CACHE_DIR,
    FEET_TO_M,
    ISLAND_EXCLUSIONS_WGS84,
    TARGET_CRS,
    Scope,
)
from shadeway_pipeline.sources.fetch import socrata_geojson
from shadeway_pipeline.sources.resolve import load_datasets

# CSCL rw_type, VERIFIED 2026-08-20 by sampling full_street_name per code:
#   1 street, 2 highway, 3 bridge, 6 path/trail, 7 pedestrian overpass,
#   9 ramp, 10 alley, 12 non-physical, 13 connector, 14 ferry route.
# 36,702 segments match in Manhattan + Brooklyn.
WALKABLE_RW_TYPES = {"1", "6", "7", "10"}

PREFETCHED = CACHE_DIR / "centerline.geojson"  # written by data/cache/fetch_nyc.sh


def _download(scope: Scope) -> Path:
    if PREFETCHED.exists():
        return PREFETCHED
    where = "boroughcode in (" + ",".join(f"'{b}'" for b in scope.boroughs) + ")"
    return socrata_geojson(load_datasets()["street_centerline"], where=where)


def _in_excluded_island(lon: float, lat: float) -> bool:
    return any(
        w <= lon <= e and s <= lat <= n
        for w, s, e, n in ISLAND_EXCLUSIONS_WGS84
    )


def load(scope: Scope) -> gpd.GeoDataFrame:
    frame = gpd.read_file(_download(scope))
    if "rw_type" in frame.columns:
        frame = frame[frame["rw_type"].astype(str).isin(WALKABLE_RW_TYPES)]
    frame = frame[frame["boroughcode"].astype(str).isin(scope.boroughs)]
    # geometry arrives as MultiLineString — explode before anything else
    frame = frame.explode(index_parts=False)
    # Reproject BEFORE taking midpoints. Interpolating along a geographic CRS
    # measures distance in degrees, which is not a distance; geopandas warns
    # about exactly this. At normalized 0.5 the answer barely moves, but the
    # warning is right and projecting first costs nothing here.
    frame = gpd.GeoDataFrame(frame, geometry="geometry").to_crs(TARGET_CRS)
    # drop geographically separate landmasses (see ISLAND_EXCLUSIONS_WGS84)
    mids = frame.geometry.interpolate(0.5, normalized=True)
    mids_wgs84 = mids.to_crs("EPSG:4326")
    keep_mask = ~np.array(
        [_in_excluded_island(p.x, p.y) for p in mids_wgs84]
    )
    frame = frame[keep_mask]

    if "streetwidth" in frame.columns:
        width_ft = pd.to_numeric(frame["streetwidth"], errors="coerce")
    else:
        width_ft = pd.Series(float("nan"), index=frame.index)
    street_width_m = width_ft * FEET_TO_M

    out = gpd.GeoDataFrame(
        {
            "physical_id": frame["physicalid"].astype("int64"),
            "street_name": frame["full_street_name"].fillna("").str.title(),
            "borough": frame["boroughcode"].astype(str),
            # metres; NaN where CSCL has no width (7.2%) — build.offset_for falls back
            "street_width_m": street_width_m.values,
            "geometry": frame.geometry.values,
        },
        crs=TARGET_CRS,
    )
    out = out[out.geometry.notna() & (out.geometry.geom_type == "LineString")]
    return out.reset_index(drop=True)
