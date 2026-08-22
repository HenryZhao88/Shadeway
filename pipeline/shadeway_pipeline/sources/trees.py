"""2015 Street Tree Census. The fidelity dataset: species + trunk diameter for
every street tree, 232k alive in Manhattan + Brooklyn.

TRAP (DATA-FINDINGS #7b): the GeoJSON returns `"geometry": null` on every row.
Build points from the `longitude` / `latitude` property columns instead — do
NOT use gpd.read_file's default geometry handling and check for silent nulls.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from shadeway_pipeline.config import CACHE_DIR, TARGET_CRS, Scope
from shadeway_pipeline.sources.fetch import socrata_geojson
from shadeway_pipeline.sources.resolve import load_datasets

INCH_TO_CM = 2.54
MAX_DBH_IN = 60.0  # census maxima run to 425 in; anything over 60 in is an error

PREFETCHED = CACHE_DIR / "trees.geojson"  # written by data/cache/fetch_nyc.sh


def _download(scope: Scope) -> Path:
    if PREFETCHED.exists():
        return PREFETCHED
    where = "status == 'Alive' AND borocode in (" + ",".join(
        f"'{b}'" for b in scope.boroughs
    ) + ")"
    return socrata_geojson(load_datasets()["trees"], where=where)


def load(scope: Scope) -> gpd.GeoDataFrame:
    frame = pd.read_json(_download(scope), lines=False)
    features = frame["features"] if "features" in frame.columns else None
    if features is not None:
        props = pd.DataFrame([f["properties"] for f in features])
    else:
        props = frame

    lon = pd.to_numeric(props["longitude"], errors="coerce")
    lat = pd.to_numeric(props["latitude"], errors="coerce")
    points = gpd.GeoDataFrame(
        {
            "species": props.get("spc_latin", "").fillna(""),
            "dbh_cm": (
                np.clip(
                    pd.to_numeric(props.get("tree_dbh"), errors="coerce"),
                    0,
                    MAX_DBH_IN,
                )
                * INCH_TO_CM
            ),
            "borough": props.get("borocode", "").astype(str),
        },
        geometry=gpd.points_from_xy(lon, lat),
        crs="EPSG:4326",
    )
    points = points[points.geometry.is_valid & points.geometry.notna()]
    points = points[
        (points.geometry.x > -74.3) & (points.geometry.x < -73.7)
        & (points.geometry.y > 40.5) & (points.geometry.y < 40.92)
    ]
    points = points[points["borough"].isin(scope.boroughs)]
    return points.to_crs(TARGET_CRS).reset_index(drop=True)
