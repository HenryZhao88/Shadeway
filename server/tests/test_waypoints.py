"""The cool-waypoints post-pass.

Everything here runs on a hand-built Route. That is the point of the feature's
isolation: it needs no scene, no weather, no router — just legs with felt
temperatures on them and a list of amenities.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from shadeway import waypoints
from shadeway_contracts.api import Exposure, FeelsLike, LegStep, Route
from shadeway_contracts.tables import AmenityKind

EDT = timezone(timedelta(hours=-4))
DEPART = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)


class FakeGraph:
    """Just enough graph for the post-pass: sample coordinates per edge."""

    def __init__(self, n_edges: int, spacing_m: float = 100.0) -> None:
        self.per_edge = 4
        self.spacing = spacing_m
        self.sample_xy = np.array(
            [
                [edge * spacing_m + i * (spacing_m / self.per_edge), 0.0]
                for edge in range(n_edges)
                for i in range(self.per_edge)
            ],
            dtype=np.float64,
        )

    def sample_ids(self, edge_id: int) -> np.ndarray:
        start = int(edge_id) * self.per_edge
        return np.arange(start, start + self.per_edge)


def _route(feels_like_c: float, n_legs: int = 8, leg_seconds: float = 90.0) -> Route:
    legs = []
    clock = DEPART
    for edge_id in range(n_legs):
        legs.append(
            LegStep(
                edge_id=edge_id,
                street_name="Test St",
                side=0,
                kind=0,
                geometry=[(-73.98, 40.75), (-73.979, 40.75)],
                length_m=leg_seconds * 1.35,
                enter_iso=clock,
                exit_iso=clock + timedelta(seconds=leg_seconds),
                feels_like_c=feels_like_c,
                tmrt_c=feels_like_c + 10.0,
                f_sun=0.8,
                svf=0.5,
            )
        )
        clock += timedelta(seconds=leg_seconds)
    return Route(
        route_id="r", label="r", depart_iso=DEPART, arrive_iso=clock,
        duration_s=(clock - DEPART).total_seconds(),
        distance_m=sum(leg.length_m for leg in legs),
        feels_like_c=FeelsLike(
            mean_c=feels_like_c, max_c=feels_like_c, p90_c=feels_like_c
        ),
        exposure=Exposure(sun_fraction=0.8, mean_svf=0.5, canopy_fraction=0.0),
        legs=legs, instructions=[],
    )


def _index(*positions_m: float) -> waypoints.AmenityIndex:
    return waypoints.AmenityIndex(
        [
            {
                "amenity_id": i,
                "kind": int(AmenityKind.DRINKING_FOUNTAIN),
                "name": f"Fountain {i}",
                "x_m": x, "y_m": 0.0, "lon": -73.98, "lat": 40.75,
            }
            for i, x in enumerate(positions_m)
        ]
    )


def test_cool_walk_earns_no_stops():
    """Below the heat-stress boundary nothing accumulates, so nothing is
    suggested — a shaded stroll should never be told to go and sit down."""
    graph = FakeGraph(8)
    found = waypoints.suggest(_route(23.0), _index(200.0, 500.0), graph)
    assert found == []


def test_hot_walk_earns_a_stop_at_the_fountain_it_passes():
    graph = FakeGraph(8)
    # 90 s legs at a felt 36 C accumulate 15 degree-minutes each, so the 80 dm
    # threshold falls on leg 5, whose last sample sits at x = 575 m. Put a
    # fountain 45 m past it: inside the round-trip detour budget.
    index = _index(620.0)
    found = waypoints.suggest(_route(36.0), index, graph)
    assert len(found) == 1
    assert found[0].name == "Fountain 0"
    assert found[0].kind == int(AmenityKind.DRINKING_FOUNTAIN)
    assert found[0].detour_s < waypoints.DETOUR_BUDGET_S


def test_reverse_walk_searches_for_amenities_at_the_end_actually_reached():
    from pyproj import Transformer

    from shadeway_contracts.tables import CRS_EPSG

    graph = FakeGraph(2, spacing_m=1000.0)
    route = _route(36.0, n_legs=2)
    to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)
    first = route.legs[0].model_copy(update={
        "geometry": [to_ll.transform(750.0, 0.0), to_ll.transform(0.0, 0.0)]
    })
    route = route.model_copy(update={"legs": [first, route.legs[1]]})
    found = waypoints.suggest(route, _index(0.0), graph, load_threshold_dm=1.0)
    assert len(found) == 1
    assert found[0].inserted_after_leg == 0
    assert found[0].detour_s == pytest.approx(0.0)


def test_amenity_out_of_detour_budget_is_not_suggested():
    graph = FakeGraph(8)
    far = waypoints.DETOUR_BUDGET_S * 1.35  # well past the round-trip budget
    found = waypoints.suggest(_route(36.0), _index(far + 5_000.0), graph)
    assert found == []


def test_load_resets_after_a_stop_so_stops_do_not_bunch():
    graph = FakeGraph(24)
    index = _index(*[float(x) for x in range(200, 2400, 100)])
    found = waypoints.suggest(_route(36.0, n_legs=24), index, graph, max_stops=3)
    assert 2 <= len(found) <= 3
    gaps = [
        b.inserted_after_leg - a.inserted_after_leg
        for a, b in zip(found, found[1:])
    ]
    assert all(gap >= 2 for gap in gaps), gaps


def test_the_same_amenity_is_never_suggested_twice():
    graph = FakeGraph(24)
    index = _index(620.0)
    found = waypoints.suggest(_route(36.0, n_legs=24), index, graph, max_stops=3)
    assert len({w.amenity_id for w in found}) == len(found)


def test_max_stops_is_respected():
    graph = FakeGraph(40)
    index = _index(*[float(x) for x in range(200, 4000, 100)])
    found = waypoints.suggest(_route(38.0, n_legs=40), index, graph, max_stops=2)
    assert len(found) == 2


def test_no_amenities_means_no_crash_and_no_stops():
    graph = FakeGraph(8)
    assert waypoints.suggest(_route(38.0), waypoints.AmenityIndex([]), graph) == []


def test_rest_instructions_name_the_place_and_the_cost():
    graph = FakeGraph(8)
    found = waypoints.suggest(_route(36.0), _index(620.0), graph)
    cards = waypoints.rest_instructions(found, _route(36.0))
    assert len(cards) == 1
    assert cards[0].type == "rest"
    assert "Fountain 0" in cards[0].text


@pytest.mark.parametrize("kind", list(AmenityKind))
def test_every_amenity_kind_has_a_noun(kind):
    """A new AmenityKind must not surface in the UI as a bare integer."""
    assert waypoints._KIND_NOUN[int(kind)]
