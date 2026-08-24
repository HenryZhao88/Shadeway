"""Derived park entrances.

The derivation is the interesting part, so it is tested against hand-built
geometry rather than the downloaded dataset: a square park, and sidewalks along
some of its sides. No network, no fixtures.
"""

import numpy as np
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon

from shadeway_pipeline.sources import parks


def _square(x0: float, y0: float, side: float) -> Polygon:
    return Polygon(
        [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    )


def test_boundary_samples_walk_the_whole_outline():
    park = _square(0.0, 0.0, 400.0)
    points = parks._boundary_samples(park)
    perimeter = park.exterior.length
    assert len(points) == pytest.approx(perimeter / parks.BOUNDARY_STEP_M, rel=0.1)
    # every sample sits on the boundary, not inside it
    for point in points:
        assert park.exterior.distance(point) < 1e-6


def test_boundary_samples_handle_multipolygon_parks():
    park = MultiPolygon([_square(0.0, 0.0, 100.0), _square(500.0, 0.0, 100.0)])
    points = parks._boundary_samples(park)
    xs = np.array([p.x for p in points])
    assert xs.min() < 200.0 and xs.max() > 400.0, "one of the two parts was dropped"


def test_non_polygon_geometry_is_ignored_rather_than_crashing():
    assert parks._boundary_samples(LineString([(0, 0), (1, 1)])) == []


def test_cluster_enforces_a_minimum_separation():
    step = parks.CLUSTER_SEPARATION_M / 10.0
    points = [_point(i * step, 0.0) for i in range(60)]
    kept = parks._cluster(points, limit=100)
    assert len(kept) > 1
    for a, b in zip(kept, kept[1:]):
        assert a.distance(b) >= parks.CLUSTER_SEPARATION_M - 1e-6


def test_cluster_spreads_the_cap_around_the_park_rather_than_taking_a_run():
    """The bug this guards: greedily stopping at the cap gives a big park eight
    entrances along one block and none on the other three sides."""
    step = parks.CLUSTER_SEPARATION_M
    points = [_point(i * step, 0.0) for i in range(80)]
    kept = parks._cluster(points, limit=4)
    assert len(kept) == 4
    span = kept[-1].x - kept[0].x
    assert span > 0.8 * (points[-1].x - points[0].x), (
        f"entrances bunched into {span:.0f} m of a "
        f"{points[-1].x - points[0].x:.0f} m boundary"
    )


def test_cluster_is_deterministic():
    points = [_point(i * 30.0, 0.0) for i in range(40)]
    first = [(p.x, p.y) for p in parks._cluster(points, limit=5)]
    second = [(p.x, p.y) for p in parks._cluster(points, limit=5)]
    assert first == second


def test_no_sidewalks_means_no_entrances(monkeypatch):
    """Deriving entrances with nothing to check reachability against would be
    inventing them, so the honest answer is none."""
    monkeypatch.setattr(parks, "load_polygons", lambda scope: _park_frame())
    assert len(parks.entrances(_scope(), None)) == 0
    assert len(parks.entrances(_scope(), [])) == 0


def test_entrances_appear_only_where_a_sidewalk_reaches_the_boundary(monkeypatch):
    monkeypatch.setattr(parks, "load_polygons", lambda scope: _park_frame())
    # one sidewalk running along the park's southern edge only
    sidewalk = LineString([(0.0, -5.0), (400.0, -5.0)])
    found = parks.entrances(_scope(), [sidewalk])
    assert len(found)
    ys = np.array([g.y for g in found.geometry])
    assert (ys < parks.SIDEWALK_REACH_M).all(), (
        "an entrance was placed on a side of the park with no sidewalk"
    )
    assert all(name.endswith("entrance") for name in found["name"])
    assert all("Test Park" in name for name in found["name"])


def test_entrance_count_is_capped_per_park(monkeypatch):
    monkeypatch.setattr(parks, "load_polygons", lambda scope: _park_frame(side=4000.0))
    ring = LineString(
        [(-5.0, -5.0), (4005.0, -5.0), (4005.0, 4005.0), (-5.0, 4005.0), (-5.0, -5.0)]
    )
    found = parks.entrances(_scope(), [ring])
    assert 0 < len(found) <= parks.MAX_ENTRANCES_PER_PARK


# ------------------------------------------------------------------ helpers


def _point(x: float, y: float):
    import shapely

    return shapely.points(x, y)


def _park_frame(side: float = 400.0):
    import geopandas as gpd

    from shadeway_pipeline.config import TARGET_CRS

    return gpd.GeoDataFrame(
        {"signname": ["Test Park"], "class": ["PARK"], "acres": ["10"]},
        geometry=[_square(0.0, 0.0, side)],
        crs=TARGET_CRS,
    )


def _scope():
    from shadeway_pipeline.config import SCOPES

    return SCOPES["midtown"]
