"""Park entrances, derived — because NYC does not publish them.

DATA-FINDINGS: there is no park-entrance dataset on NYC Open Data. Searching
the Socrata catalog for "Park Entrance" returns the NYCHA data book and
waterfront public access points; nothing about park gates. What does exist is
Parks Properties (enfh-gkve, 2,064 polygons citywide) with `signname`,
`class` and `typecategory`.

So an entrance is derived rather than looked up, and derived from the only
definition we can actually defend: a park entrance is a point on the park
boundary that a pedestrian can reach, i.e. a boundary point within a few metres
of the sidewalk network we route on. That makes the derivation depend on the
graph, which is why `load` takes sidewalk geometries and returns nothing
without them — inventing entrances with no network to check against would be
worse than having none.

The points are clustered so a large park contributes a handful of usable
entrances rather than a hundred boundary samples, and capped per park so
Central Park cannot drown out every fountain in the amenity layer.
"""

from __future__ import annotations

import numpy as np

from shadeway_pipeline.config import CACHE_DIR, TARGET_CRS, Scope
from shadeway_pipeline.sources.fetch import socrata_geojson

DATASET_KEY = "parks_properties"
DATASET_ID = "enfh-gkve"
PREFETCHED = CACHE_DIR / "parks_properties.geojson"

# Which Parks properties are places you would actually walk into to cool off.
# Parking lots, "Undeveloped" sites and the landscaped medians filed as "Mall"
# (Broadway Malls, Park Avenue) are parkland on paper: you cannot sit in a
# median between two lanes of traffic, and offering one as a rest stop would
# discredit every other suggestion on the route.
WALKABLE_CLASSES = {"PARK", "NATURE AREA", "HISTORIC HOUSE PARK", "COMMUNITY PARK"}
EXCLUDED_CATEGORIES = {
    "Parkway", "Undeveloped", "Strip", "Tracking",
    "Buildings/Institutions", "Lot", "Mall",
}

BOUNDARY_STEP_M = 15.0  # how finely the park edge is walked looking for access
SIDEWALK_REACH_M = 15.0  # boundary within this of a sidewalk is reachable
CLUSTER_SEPARATION_M = 80.0  # two gates closer than this are one entrance
MAX_ENTRANCES_PER_PARK = 8
MIN_PARK_ACRES = 0.25  # below this it is a planted triangle, not somewhere to sit


def _download() -> "object":
    if PREFETCHED.exists():
        return PREFETCHED
    return socrata_geojson(DATASET_ID)


def load_polygons(scope: Scope):
    """Park polygons inside the scope, in TARGET_CRS. Empty frame on failure."""
    import geopandas as gpd

    try:
        path = _download()
        frame = gpd.read_file(path)
    except Exception:
        return None

    if not len(frame):
        return None
    if "class" in frame.columns:
        keep = frame["class"].fillna("").str.upper().isin(WALKABLE_CLASSES)
        frame = frame[keep]
    if "typecategory" in frame.columns:
        frame = frame[~frame["typecategory"].fillna("").isin(EXCLUDED_CATEGORIES)]
    if "acres" in frame.columns:
        acres = frame["acres"].astype(str).str.replace(",", "")
        frame = frame[
            acres.pipe(lambda s: s.where(s.str.len() > 0, "0")).astype(float)
            >= MIN_PARK_ACRES
        ]
    if not len(frame):
        return None

    west, south, east, north = scope.bbox_wgs84
    frame = frame.to_crs("EPSG:4326").cx[west:east, south:north]
    if not len(frame):
        return None
    return frame.to_crs(TARGET_CRS).reset_index(drop=True)


def entrances(scope: Scope, sidewalk_geoms) -> "object":
    """GeoDataFrame of derived entrance points (columns: name, geometry).

    `sidewalk_geoms` is any iterable of sidewalk LineStrings in TARGET_CRS —
    the pipeline hands it the edges it has just built. With none, this returns
    an empty frame: see the module docstring for why that is the right answer
    rather than a guess.
    """
    import geopandas as gpd
    import shapely
    from shapely.strtree import STRtree

    empty = gpd.GeoDataFrame({"name": [], "geometry": []}, crs=TARGET_CRS)
    geoms = list(sidewalk_geoms) if sidewalk_geoms is not None else []
    if not geoms:
        return empty
    parks = load_polygons(scope)
    if parks is None or not len(parks):
        return empty

    index = STRtree(geoms)
    names: list[str] = []
    points: list[object] = []

    for _, park in parks.iterrows():
        reachable = [
            point
            for point in _boundary_samples(park.geometry)
            if len(index.query(shapely.buffer(point, SIDEWALK_REACH_M)))
        ]
        # cluster per park, so the cap is per park: Central Park gets eight
        # entrances, not eight hundred boundary samples
        kept = _cluster(reachable, MAX_ENTRANCES_PER_PARK)
        label = _park_name(park)
        points.extend(kept)
        names.extend([f"{label} entrance"] * len(kept))

    if not points:
        return empty
    return gpd.GeoDataFrame({"name": names}, geometry=points, crs=TARGET_CRS)


def _park_name(park) -> str:
    for column in ("signname", "name311", "location"):
        value = park.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Park"


def _boundary_samples(geometry) -> list:
    """Points every BOUNDARY_STEP_M around a park's outline."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon

    polygons: list[Polygon] = []
    if isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    elif isinstance(geometry, Polygon):
        polygons = [geometry]
    else:
        return []

    out = []
    for polygon in polygons:
        ring = polygon.exterior
        if ring is None or ring.length <= 0:
            continue
        count = max(4, int(ring.length // BOUNDARY_STEP_M))
        distances = np.linspace(0.0, ring.length, count, endpoint=False)
        out.extend(shapely.line_interpolate_point(ring, distances).tolist())
    return out


def _cluster(points: list, limit: int) -> list:
    """Thin to distinct gates, then spread the survivors around the park.

    Two steps, and the second one matters: stopping the greedy pass at `limit`
    would hand Central Park eight entrances in a row down one block of Fifth
    Avenue and none on the other three sides. So thin the whole boundary first,
    then take an evenly spaced subset of what survives.

    Deterministic in input order, which is boundary order — amenity_id is a row
    index and the client caches pins by it.
    """
    if not points:
        return []
    xs = np.array([p.x for p in points])
    ys = np.array([p.y for p in points])
    kept_idx: list[int] = []
    for i in range(len(points)):
        if kept_idx:
            gap = np.hypot(xs[kept_idx] - xs[i], ys[kept_idx] - ys[i]).min()
            if gap < CLUSTER_SEPARATION_M:
                continue
        kept_idx.append(i)
    if len(kept_idx) > limit:
        picks = np.linspace(0, len(kept_idx) - 1, limit).round().astype(int)
        kept_idx = [kept_idx[i] for i in dict.fromkeys(picks.tolist())]
    return [points[i] for i in kept_idx]
