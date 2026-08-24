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


def _text_column(frame, name: str) -> pd.Series:
    """A string column, or an empty one of the right length if it is missing.

    Species drives tau, and an unknown species falls back to the global default
    with `tau_source = "default"` — which is honest. Crashing the whole build
    because one optional column moved is not.
    """
    if name in frame.columns:
        return frame[name].fillna("").astype(str)
    return pd.Series([""] * len(frame), index=frame.index, dtype=object)


def load(scope: Scope) -> gpd.GeoDataFrame:
    # gpd.read_file parses the FeatureCollection (geometry is null everywhere —
    # we ignore it) and hands back the property columns
    props = gpd.read_file(_download(scope))
    lon = pd.to_numeric(props["longitude"], errors="coerce")
    lat = pd.to_numeric(props["latitude"], errors="coerce")
    points = gpd.GeoDataFrame(
        {
            # `props.get(col, "")` hands back a bare str when the column is
            # absent, and a str has no .fillna — so an export missing spc_latin
            # crashed here instead of degrading to unknown species.
            "species": _text_column(props, "spc_latin"),
            "dbh_cm": (
                np.clip(
                    pd.to_numeric(props.get("tree_dbh"), errors="coerce"),
                    0,
                    MAX_DBH_IN,
                )
                * INCH_TO_CM
            ),
            "borough": _text_column(props, "borocode"),
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
