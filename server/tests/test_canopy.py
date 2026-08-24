import numpy as np
from shapely import STRtree
import shapely

from shadeway import occluder
from shadeway.scene import Scene


def _crowns(offsets, tau, radius=4.0, base=2.5, top=10.0) -> Scene:
    xy = np.array([[dx, dy] for dx, dy in offsets], dtype=np.float64)
    points = [shapely.points(x, y) for x, y in xy]
    n = len(xy)
    return Scene(
        building_geoms=[],
        building_heights_m=np.zeros(0, dtype=np.float32),
        building_bases_m=np.zeros(0, dtype=np.float32),
        building_tree=STRtree([]),
        tree_xy=xy,
        tree_radius_m=np.full(n, radius, dtype=np.float32),
        crown_base_m=np.full(n, base, dtype=np.float32),
        crown_top_m=np.full(n, top, dtype=np.float32),
        tau=np.full(n, tau, dtype=np.float32),
        tree_tree=STRtree(points),
    )


def test_open_sky_transmits_everything():
    scene = _crowns([], 0.35)
    assert occluder.canopy_transmittance(scene, 0.0, 0.0, 0.0, 45.0) == 1.0


def test_one_airy_crown_transmits_its_tau():
    # crown centred 10 m north; at 45 deg elevation the ray is ~11 m up there,
    # so widen the crown vertically to make sure it is intercepted
    scene = _crowns([(0.0, 10.0)], 0.35, base=2.0, top=20.0)
    assert abs(occluder.canopy_transmittance(scene, 0.0, 0.0, 0.0, 45.0) - 0.35) < 1e-5


def test_two_crowns_multiply():
    scene = _crowns([(0.0, 10.0), (0.0, 25.0)], 0.35, base=2.0, top=30.0)
    got = occluder.canopy_transmittance(scene, 0.0, 0.0, 0.0, 45.0)
    assert abs(got - 0.35 * 0.35) < 1e-4


def test_a_crown_the_ray_passes_over_is_ignored():
    """Crown tops out at 4 m; at 45 deg the ray is 11 m up by the time it gets there."""
    scene = _crowns([(0.0, 10.0)], 0.35, base=2.0, top=4.0)
    assert occluder.canopy_transmittance(scene, 0.0, 0.0, 0.0, 45.0) == 1.0


def test_a_crown_the_ray_passes_under_is_ignored():
    """Crown starts at 15 m; at 5 deg elevation the ray is under 2 m at 10 m out."""
    scene = _crowns([(0.0, 10.0)], 0.35, base=15.0, top=25.0)
    assert occluder.canopy_transmittance(scene, 0.0, 0.0, 0.0, 5.0) == 1.0


def test_dense_species_shade_harder_than_airy_ones():
    airy = _crowns([(0.0, 10.0)], 0.35, base=2.0, top=20.0)
    dense = _crowns([(0.0, 10.0)], 0.15, base=2.0, top=20.0)
    assert occluder.canopy_transmittance(dense, 0.0, 0.0, 0.0, 45.0) < (
        occluder.canopy_transmittance(airy, 0.0, 0.0, 0.0, 45.0)
    )


def test_f_sun_is_zero_when_a_building_blocks_regardless_of_canopy():
    from shapely.geometry import Polygon

    scene = _crowns([(0.0, 10.0)], 0.35, base=2.0, top=20.0)
    poly = Polygon([(-10, 20), (10, 20), (10, 30), (-10, 30)])
    scene.building_geoms = [poly]
    scene.building_heights_m = np.array([100.0], dtype=np.float32)
    scene.building_bases_m = np.array([0.0], dtype=np.float32)
    scene.building_tree = STRtree([poly])
    assert occluder.f_sun(scene, 0.0, 0.0, 0.0, 45.0) == 0.0


def test_canopy_profile_shape_and_dtype():
    scene = _crowns([(0.0, 10.0)], 0.35, base=2.0, top=20.0)
    profile = occluder.canopy_horizon_profile(scene, 0.0, 0.0)
    assert profile.shape == (72,) and profile.dtype == np.uint8


def test_canopy_profile_peaks_only_toward_the_crown():
    """One crown due north must raise bin 0 and nothing else — a crown to the
    side or behind cannot shade a direction it is not in."""
    scene = _crowns([(0.0, 10.0)], 0.35, radius=4.0, base=2.0, top=20.0)
    profile = occluder.canopy_horizon_profile(scene, 0.0, 0.0)
    assert profile[0] > 0, "bin 0 is due north, where the crown is"
    assert profile[36] == 0, "bin 36 is due south; the crown is behind us"
    far = [b for b in range(72) if 8 <= b % 72 <= 28]
    assert all(profile[b] == 0 for b in far), (
        "bins pointing away from the crown must stay clear"
    )


def test_a_crown_behind_the_point_never_shades_the_opposite_side():
    scene = _crowns([(0.0, -12.0)], 0.35, radius=4.0, base=2.0, top=20.0)
    profile = occluder.canopy_horizon_profile(scene, 0.0, 0.0)
    # a 4 m crown 12 m away subtends about +/-19 deg, so bins 32..40 may graze
    # it; everything on the far side of the compass must stay clear
    clear = [b for b in range(72) if not 31 <= b <= 41]
    assert all(profile[b] == 0 for b in clear), (
        "a crown due south cannot shade the northern half of the sky"
    )
