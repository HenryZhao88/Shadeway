from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from shadeway.cost import EdgeCostModel, canopy_fraction
from shadeway.horizon import HorizonCache
from shadeway.router.graph import Graph
from shadeway.scene import Scene
from shadeway_contracts.api import WeatherSnapshot
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))
NOON = datetime(2025, 7, 22, 13, 0, tzinfo=EDT)

WEATHER = WeatherSnapshot(
    observed_iso=NOON, air_temp_c=30.6, relative_humidity_pct=48.0,
    wind_speed_10m_ms=2.0, cloud_cover_pct=6.0, direct_normal_wm2=799.0,
    diffuse_wm2=148.0, global_horizontal_wm2=712.0, uv_index=8.0,
)


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    data = tmp_path_factory.mktemp("cost")
    write_fixture_city(data)
    graph = Graph.load(data)
    scene = Scene.load(data)
    cache = HorizonCache(scene, graph.sample_xy)
    cost = EdgeCostModel(
        horizon=cache, weather=WEATHER, sample_albedo=graph.sample_albedo,
        lat=40.7536, lon=-73.9840, walk_speed_ms=1.35,
    )
    cost.bind_graph(graph)  # traverse() reads edge attributes through this
    return graph, cost


def test_duration_is_length_over_speed(model):
    graph, cost = model
    result = cost.traverse(0, NOON)
    assert abs(result.duration_s - graph.edge_length_m[0] / 1.35) < 20.0


def test_crossings_carry_a_waiting_penalty(model):
    graph, cost = model
    crossing = int(np.flatnonzero(graph.edge_kind == 1)[0])
    sidewalk = int(np.flatnonzero(graph.edge_kind == 0)[0])
    per_metre_crossing = (
        cost.traverse(crossing, NOON).duration_s / graph.edge_length_m[crossing]
    )
    per_metre_sidewalk = (
        cost.traverse(sidewalk, NOON).duration_s / graph.edge_length_m[sidewalk]
    )
    assert per_metre_crossing > per_metre_sidewalk


def test_heat_cost_is_degree_minutes(model):
    graph, cost = model
    result = cost.traverse(0, NOON)
    expected = result.mean_feels_like_c * (result.duration_s / 60.0)
    assert abs(result.heat_degree_minutes - expected) < 1e-3


def test_the_same_edge_is_hotter_at_noon_than_at_dusk(model):
    graph, cost = model
    noon = cost.traverse(0, NOON)
    dusk = cost.traverse(0, NOON.replace(hour=20))
    assert noon.mean_feels_like_c > dusk.mean_feels_like_c


def test_f_sun_and_svf_are_reported_for_the_ui(model):
    graph, cost = model
    result = cost.traverse(0, NOON)
    assert 0.0 <= result.mean_f_sun <= 1.0
    assert 0.0 <= result.mean_svf <= 1.0


def test_canopy_is_classified_before_edge_sun_is_averaged():
    # Both arrays average to 0.5. Only the second is transmissive canopy; the
    # first is a mix of opaque building shade and open sky.
    assert canopy_fraction(np.array([0.0, 1.0])) == 0.0
    assert canopy_fraction(np.array([0.38, 0.62])) == 1.0


def test_the_router_never_needs_to_import_thermal():
    """The cost model is a callable. That is the entire coupling."""
    import inspect

    import shadeway.router.graph as router_graph

    assert "thermal" not in inspect.getsource(router_graph)
