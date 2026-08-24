"""Cool-water amenities: drinking fountains, Cool It! cooling sites, spray
showers, and derived park entrances.

NOTE (DATA-FINDINGS #9): no "cooling center" dataset exists on NYC Open Data —
the official finder is a separate app. The Cool It! datasets (misting stations,
hydrant spray caps) plus spray showers stand in, honestly labelled. Their `x`/`y`
columns are LON/LAT despite the names.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from shadeway_pipeline.config import CACHE_DIR, TARGET_CRS, Scope
from shadeway_pipeline.sources import parks

PREFETCHED = {
    "fountains": CACHE_DIR / "fountains.geojson",
    "cooling_sites": CACHE_DIR / "coolit_cooling_sites.json",
    "spray_showers": CACHE_DIR / "coolit_spray_showers.json",
}


def _read_features(path: Path) -> pd.DataFrame:
    """Read a GeoJSON or plain-JSON feature file into a properties DataFrame.

    pd.read_json cannot handle a FeatureCollection whose values are dicts
    ("Mixing dicts with non-Series"), so parse explicitly.
    """
    import json

    data = json.loads(path.read_text())
    if isinstance(data, list):
        # Cool It! files are bare arrays of flat objects with x/y lon-lat
        return pd.DataFrame(data)
    features = data.get("features", [])
    if features:
        return pd.DataFrame(
            [
                {"properties": f.get("properties", {}), "geometry": f.get("geometry")}
                for f in features
            ]
        )
    return pd.DataFrame(data)


def _load_geojson_points(path: Path) -> gpd.GeoDataFrame:
    props = _read_features(path)
    if "properties" in props.columns and "geometry" in props.columns:
        geoms = props["geometry"]
        props = pd.DataFrame(list(props["properties"]))
        lon = [g["coordinates"][0] if g else None for g in geoms]
        lat = [g["coordinates"][1] if g else None for g in geoms]
    else:
        lon = props["x"]  # Cool It! json: x/y ARE lon/lat despite the names
        lat = props["y"]
    return gpd.GeoDataFrame(
        {"name": _names(props)},
        geometry=gpd.points_from_xy(pd.to_numeric(lon, errors="coerce"),
                                    pd.to_numeric(lat, errors="coerce")),
        crs="EPSG:4326",
    )


def _names(props: pd.DataFrame) -> pd.Series:
    """Whatever this source calls the place.

    The Parks fountains export truncates its column names to ten characters
    ("propertyna", "decription" — their typo, not ours), which is why the short
    forms are in this list. Without them every fountain arrives nameless and
    the rest-stop card reads "Cool off at Drinking fountain".
    """
    for col in (
        "name", "site_name", "park_name", "propertyname",
        "propertyna", "signname", "decription", "description",
    ):
        if col in props.columns:
            values = props[col].fillna("").astype(str).str.strip()
            if values.str.len().gt(0).any():
                return values
    return pd.Series([""] * len(props))


def load(scope: Scope, sidewalk_geoms=None) -> gpd.GeoDataFrame:
    """`sidewalk_geoms` (EPSG:32118 LineStrings, normally the edges the graph
    build just produced) unlocks AmenityKind.PARK_ENTRANCE. Park entrances are
    not published by the city and are derived against the pedestrian network —
    see sources/parks.py. Without the network they are simply absent, and the
    other two kinds are unaffected."""
    parts: list[tuple[int, gpd.GeoDataFrame]] = []

    if PREFETCHED["fountains"].exists():
        fountains = _load_geojson_points(PREFETCHED["fountains"])
        parts.append((0, fountains))  # AmenityKind.DRINKING_FOUNTAIN

    for key in ("cooling_sites", "spray_showers"):
        path = PREFETCHED[key]
        if not path.exists():
            continue
        props = _read_features(path)
        lon = props.get("longitude", props.get("x"))
        lat = props.get("latitude", props.get("y"))
        pts = gpd.GeoDataFrame(
            {"name": _names(props)},
            geometry=gpd.points_from_xy(pd.to_numeric(lon, errors="coerce"),
                                        pd.to_numeric(lat, errors="coerce")),
            crs="EPSG:4326",
        )
        parts.append((1, pts))  # AmenityKind.COOLING_CENTER

    gates = parks.entrances(scope, sidewalk_geoms)
    if len(gates):
        parts.append((2, gates.to_crs("EPSG:4326")))  # AmenityKind.PARK_ENTRANCE

    if not parts:
        return gpd.GeoDataFrame(
            {"kind": [], "name": [], "geometry": []}, crs=TARGET_CRS
        )

    frames = []
    for kind, frame in parts:
        frame = frame.copy()
        frame["kind"] = kind
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out = gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")
    out = out[out.geometry.notna() & out.geometry.is_valid]
    wgs_box = scope.bbox_wgs84
    out = out[
        (out.geometry.x > wgs_box[0]) & (out.geometry.x < wgs_box[2])
        & (out.geometry.y > wgs_box[1]) & (out.geometry.y < wgs_box[3])
    ]
    return out.to_crs(TARGET_CRS).reset_index(drop=True)
