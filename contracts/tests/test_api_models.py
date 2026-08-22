import json
from itertools import pairwise

import pytest
from pydantic import ValidationError
from shadeway_contracts.api import (
    PRESET_PROFILES,
    LatLon,
    RouteRequest,
    RouteResponse,
)
from shadeway_contracts.fixtures import example_route_response


def test_presets_match_the_spec():
    assert PRESET_PROFILES["standard"].minutes_per_degree == 1.0
    assert PRESET_PROFILES["sensitive"].minutes_per_degree == 3.0
    assert PRESET_PROFILES["high_risk"].minutes_per_degree == 6.0


def test_request_defaults_to_time_dependent_sun():
    req = RouteRequest(
        origin=LatLon(lat=40.7549, lon=-73.9840),
        destination=LatLon(lat=40.7484, lon=-73.9857),
        depart_iso="2025-07-22T15:00:00-04:00",
    )
    assert req.time_dependent is True
    assert req.profile.minutes_per_degree == 1.0


def test_departure_time_must_carry_a_timezone():
    with pytest.raises(ValidationError):
        RouteRequest(
            origin=LatLon(lat=40.75, lon=-73.98),
            destination=LatLon(lat=40.74, lon=-73.98),
            depart_iso="2025-07-22T15:00:00",  # naive -> rejected
        )


def test_response_round_trips_through_json():
    resp = example_route_response()
    reparsed = RouteResponse.model_validate(json.loads(resp.model_dump_json()))
    assert reparsed == resp


def test_the_hero_number_is_degrees_not_percent():
    resp = example_route_response()
    route = resp.routes[resp.chosen_route_id]
    assert route.feels_like_c.mean_c > 0
    # weather fields like relative_humidity_pct are fine; the hero output must
    # never be a shade percentage
    dumped = resp.model_dump_json()
    assert "shade_pct" not in dumped
    assert "percent" not in dumped
    for route_obj in resp.routes.values():
        for leg in route_obj.legs:
            assert not hasattr(leg, "shade_pct")


def test_every_leg_knows_which_side_of_the_street_it_is_on():
    resp = example_route_response()
    for route in resp.routes.values():
        for leg in route.legs:
            assert leg.side in (-1, 0, 1)


def test_frontier_is_sorted_by_duration_and_strictly_pareto():
    resp = example_route_response()
    pts = resp.frontier
    assert pts == sorted(pts, key=lambda p: p.duration_s)
    for a, b in pairwise(pts):
        assert b.duration_s > a.duration_s
        assert b.mean_feels_like_c < a.mean_feels_like_c
