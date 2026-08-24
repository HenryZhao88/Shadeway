
import numpy as np
import pytest

from shadeway.scene import Scene
from shadeway_contracts.fixtures import write_fixture_city


@pytest.fixture(scope="module")
def scene(tmp_path_factory) -> Scene:
    data = tmp_path_factory.mktemp("fixture-city")
    write_fixture_city(data)
    return Scene.load(data)


def test_scene_loads_buildings_and_trees(scene):
    assert len(scene.building_geoms) > 0
    assert scene.building_heights_m.shape == (len(scene.building_geoms),)
    assert scene.tree_xy.shape[1] == 2
    assert scene.tau.min() > 0.0 and scene.tau.max() < 1.0


def test_heights_are_float32_metres_not_feet(scene):
    assert scene.building_heights_m.dtype == np.float32
    assert scene.building_heights_m.max() > 100.0  # the fixture's 180 m tower
    assert scene.building_heights_m.max() < 700.0  # ...but not 590 ft misread as m


def test_buildings_near_returns_only_nearby_indices(scene):
    x, y = scene.building_geoms[0].centroid.coords[0]
    near = scene.buildings_near(x, y, 50.0)
    far = scene.buildings_near(x, y, 5000.0)
    assert 0 < len(near) < len(far)
    assert set(near) <= set(far)


def test_scene_starts_at_version_one(scene):
    assert scene.version == 1
