import numpy as np
import pytest
from shapely import STRtree
from shapely.geometry import Polygon

from shadeway import occluder
from shadeway.scene import Scene


def _one_building(height_m: float) -> Scene:
    """A 20x20 m block centred at (0, 50) — i.e. due NORTH of the origin."""
    poly = Polygon([(-10, 40), (10, 40), (10, 60), (-10, 60)])
    return Scene(
        building_geoms=[poly],
        building_heights_m=np.array([height_m], dtype=np.float32),
        building_bases_m=np.array([0.0], dtype=np.float32),
        building_tree=STRtree([poly]),
        tree_xy=np.zeros((0, 2)),
        tree_radius_m=np.zeros(0, dtype=np.float32),
        crown_base_m=np.zeros(0, dtype=np.float32),
        crown_top_m=np.zeros(0, dtype=np.float32),
        tau=np.zeros(0, dtype=np.float32),
        tree_tree=STRtree([]),
    )


def test_horizon_angle_matches_simple_trigonometry():
    """A 40 m building whose near face is 40 m away subtends atan((40-1.1)/40)."""
    scene = _one_building(40.0)
    angle = occluder.building_horizon_deg(scene, 0.0, 0.0, azimuth_deg=0.0)
    expected = np.degrees(np.arctan((40.0 - occluder.EYE_HEIGHT_M) / 40.0))
    assert abs(angle - expected) < 1.5


def test_no_obstruction_in_the_opposite_direction():
    scene = _one_building(40.0)
    assert occluder.building_horizon_deg(scene, 0.0, 0.0, azimuth_deg=180.0) == 0.0


def test_sun_below_the_horizon_angle_is_blocked():
    scene = _one_building(40.0)
    assert occluder.is_shaded_by_building(scene, 0.0, 0.0, 0.0, elevation_deg=20.0)


def test_sun_above_the_horizon_angle_gets_through():
    scene = _one_building(40.0)
    assert not occluder.is_shaded_by_building(scene, 0.0, 0.0, 0.0, elevation_deg=60.0)


def test_a_short_building_never_blocks_high_sun():
    scene = _one_building(3.0)
    assert not occluder.is_shaded_by_building(scene, 0.0, 0.0, 0.0, elevation_deg=30.0)


def test_beyond_the_ray_cap_nothing_is_seen():
    poly = Polygon([(-10, 900), (10, 900), (10, 920), (-10, 920)])
    scene = _one_building(200.0)
    scene.building_geoms = [poly]
    scene.building_tree = STRtree([poly])
    assert occluder.building_horizon_deg(scene, 0.0, 0.0, 0.0) == 0.0


def test_profile_has_the_contracted_shape_and_dtype():
    scene = _one_building(40.0)
    profile = occluder.building_horizon_profile(scene, 0.0, 0.0)
    assert profile.shape == (72,)
    assert profile.dtype == np.uint8
    assert profile.max() <= 90


def test_profile_peaks_toward_the_building():
    scene = _one_building(40.0)
    profile = occluder.building_horizon_profile(scene, 0.0, 0.0)
    assert profile[0] == profile.max(), "bin 0 is due north, where the building is"
    assert profile[36] == 0, "bin 36 is due south, which is open sky"
