from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from shadeway_contracts.api import RouteResponse, TimeseriesResponse
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    data = tmp_path_factory.mktemp("api")
    write_fixture_city(data)
    os.environ["SHADEWAY_DATA"] = str(data)
    os.environ["SHADEWAY_ENABLE_PLANTING"] = "1"
    from shadeway.api import app

    return TestClient(app)


def _body(client):
    from shadeway.api import _state

    state = _state()
    lon0, lat0 = state.graph.node_lonlat[0]
    lon1, lat1 = state.graph.node_lonlat[30]
    return {
        "origin": {"lat": float(lat0), "lon": float(lon0)},
        "destination": {"lat": float(lat1), "lon": float(lon1)},
        "depart_iso": "2025-07-22T15:00:00-04:00",
    }


def test_health_reports_the_real_scene(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["scene"] != "stub"
    assert payload["planting_enabled"] is True


def test_place_search_is_exposed_through_the_real_api(client, monkeypatch):
    from shadeway import api

    monkeypatch.setattr(
        api.GEOCODER,
        "search",
        lambda query: [
            {
                "label": f"{query}, Manhattan, New York, NY",
                "lat": 40.7536,
                "lon": -73.984,
                "kind": "park",
            }
        ],
    )
    response = client.get("/api/geocode", params={"q": "Bryant Park"})
    assert response.status_code == 200
    assert response.json()["results"][0]["label"].startswith("Bryant Park")
    assert "OpenStreetMap" in response.json()["attribution"]


def test_planting_can_be_disabled_for_public_deployments(client, monkeypatch):
    monkeypatch.setenv("SHADEWAY_ENABLE_PLANTING", "0")
    response = client.post(
        "/api/scene/plant",
        json={
            "positions": [{"lat": 40.75, "lon": -73.98}],
            "species": "Gleditsia triacanthos",
        },
    )
    assert response.status_code == 403
    assert client.get("/api/health").json()["planting_enabled"] is False


def test_one_plant_request_is_bounded(client):
    response = client.post(
        "/api/scene/plant",
        json={
            "positions": [{"lat": 40.75, "lon": -73.98}] * 41,
            "species": "Gleditsia triacanthos",
        },
    )
    assert response.status_code == 422


def test_route_returns_a_contract_valid_response(client):
    response = client.post("/api/route", json=_body(client))
    assert response.status_code == 200
    parsed = RouteResponse.model_validate(response.json())
    assert parsed.routes
    assert parsed.chosen_route_id in parsed.routes


def test_route_rejects_points_outside_the_loaded_map(client):
    body = _body(client) | {
        "destination": {"lat": 34.0522, "lon": -118.2437},
    }
    response = client.post("/api/route", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == "destination is outside the loaded map area"


def test_every_leg_reports_its_side_and_its_temperature(client):
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    for route in parsed.routes.values():
        assert route.legs
        for leg in route.legs:
            assert leg.side in (-1, 0, 1)
            assert -40.0 < leg.feels_like_c < 90.0
            assert len(leg.geometry) >= 2


def test_instructions_include_a_side_of_street_reference(client):
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    texts = [i.text for r in parsed.routes.values() for i in r.instructions]
    assert any("side" in t for t in texts), (
        "shaded-side-of-street guidance is a non-negotiable feature"
    )


def test_a_naive_departure_time_is_rejected(client):
    body = _body(client) | {"depart_iso": "2025-07-22T15:00:00"}
    assert client.post("/api/route", json=body).status_code == 422


def test_timeseries_returns_the_whole_curve_in_one_call(client):
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    route_id = parsed.chosen_route_id
    response = client.get(
        f"/api/route/{route_id}/timeseries",
        params={
            "depart_iso": "2025-07-22T15:00:00-04:00",
            "step_minutes": 5,
            "request_id": parsed.request_id,
        },
    )
    series = TimeseriesResponse.model_validate(response.json())
    assert len(series.points) >= 2


def test_timeseries_first_point_matches_the_route_it_describes(client):
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    for route_id, route in parsed.routes.items():
        series = TimeseriesResponse.model_validate(
            client.get(
                f"/api/route/{route_id}/timeseries",
                params={
                    "depart_iso": route.depart_iso.isoformat(),
                    "step_minutes": 15,
                    "hours": 1,
                    "request_id": parsed.request_id,
                },
            ).json()
        )
        assert series.points[0].mean_feels_like_c == pytest.approx(
            route.feels_like_c.mean_c
        )
        assert series.points[0].sun_fraction == pytest.approx(
            route.exposure.sun_fraction
        )


def test_timeseries_cache_is_namespaced_by_request(client):
    from shadeway.api import _recalled, _state

    first_body = _body(client)
    first = RouteResponse.model_validate(
        client.post("/api/route", json=first_body).json()
    )
    state = _state()
    lon, lat = state.graph.node_lonlat[2]
    second_body = first_body | {"origin": {"lat": float(lat), "lon": float(lon)}}
    second = RouteResponse.model_validate(
        client.post("/api/route", json=second_body).json()
    )

    assert first.request_id != second.request_id
    first_cached = _recalled(first.chosen_route_id, first.request_id)
    second_cached = _recalled(second.chosen_route_id, second.request_id)
    assert first_cached is not None and second_cached is not None
    assert first_cached[2].origin != second_cached[2].origin
    missing = client.get(
        f"/api/route/{first.chosen_route_id}/timeseries",
        params={
            "depart_iso": first.computed_at.isoformat(),
            "request_id": "not-a-real-request",
        },
    )
    assert missing.status_code == 404


def test_compute_ms_is_reported_so_we_can_see_regressions(client):
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    assert parsed.compute_ms > 0


def test_planting_a_tree_makes_the_street_cooler(client):
    """The plant endpoint must actually add crowns to the scene — returning
    'planted: 1' while changing nothing would silently fake the demo."""
    import numpy as np

    from shadeway.api import _state, _to_ll

    state = _state()
    ids = np.arange(0, 400, dtype=np.int64)

    def max_open_f_sun():
        best = 0.0
        for azimuth in range(0, 360, 10):
            values = state.horizon.f_sun(ids, float(azimuth), 20.0)
            best = max(best, float(values.max()))
        return best

    assert max_open_f_sun() == 1.0, "fixture should have fully open sample points"

    # find one open sample and aim the new crown straight at it
    target = None
    for sample_id in ids:
        if state.horizon.f_sun(np.array([sample_id]), 0.0, 20.0)[0] == 1.0:
            x, y = state.horizon.samples_xy[sample_id]
            target = (sample_id, x, y)
            break
    assert target is not None
    sample_id, sx, sy = target
    px, py = sx, sy + 5.0  # 5 m north of the sample
    lon, lat = _to_ll.transform(px, py)

    version_before = state.scene.version
    response = client.post(
        "/api/scene/plant",
        json={
            "positions": [{"lat": float(lat), "lon": float(lon)}],
            "species": "Gleditsia triacanthos",
            # dbh 25 puts the crown band (base ~3.5 m) across the beam the tau
            # profile samples at 30 deg (~4.0 m up at 5 m out); a 40 cm tree's
            # crown base is above that beam and legitimately shades nothing
            "dbh_cm": 25,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planted"] == 1
    assert body["scene_version"] == version_before + 1

    after = float(state.horizon.f_sun(np.array([sample_id]), 0.0, 20.0)[0])
    assert after < 1.0, "a crown planted 5 m north must intercept the beam"


def test_planting_invalidates_the_full_ray_reach(client, monkeypatch):
    from shadeway import occluder, scene_edit
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    observed: list[float] = []
    monkeypatch.setattr(
        state.horizon,
        "invalidate_within",
        lambda _x, _y, radius: observed.append(radius) or 0,
    )
    monkeypatch.setattr(state.scene, "plant_crowns", lambda **_kwargs: None)

    response = client.post(
        "/api/scene/plant",
        json={
            "positions": [{"lat": float(lat), "lon": float(lon)}],
            "species": "Gleditsia triacanthos",
            "dbh_cm": 25,
        },
    )
    crown_radius, *_ = scene_edit.crown_geometry("Gleditsia triacanthos", 25)
    assert response.status_code == 200
    assert observed == [pytest.approx(occluder.RAY_CAP_M + crown_radius)]


def test_departure_curve_never_emits_bare_nan_json(client, monkeypatch):
    """A failed search used to produce a literal NaN in the JSON body, which
    browser JSON.parse rejects outright."""
    from shadeway import api

    def fail(*a, **k):
        return []

    monkeypatch.setattr(api.timedep, "solve", fail)
    response = client.get(
        "/api/departure-curve",
        params={
            "origin_lat": 40.7536, "origin_lon": -73.9840,
            "dest_lat": 40.7571, "dest_lon": -73.9800,
            "from_iso": "2025-07-22T15:00:00-04:00",
            "hours": 1,
        },
    )
    assert response.status_code == 200
    assert "NaN" not in response.text, "bare NaN is not valid JSON for browsers"
    body = response.json()
    assert body["points"] == []


def test_buildings_endpoint_serves_the_occluders_the_router_uses(client):
    """The map and the routing must never disagree about what casts shade, so
    the client draws its shadows from this exact building set."""
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    response = client.get(
        "/api/buildings",
        params={"bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["buildings"], "no prisms in a bbox that covers the scene"
    assert payload["truncated"] is False
    for building in payload["buildings"]:
        assert building["height_m"] > 0
        assert len(building["polygon"]) >= 3


def test_large_api_responses_are_compressed(client):
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    response = client.get(
        "/api/buildings",
        params={"bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}"},
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


def test_buildings_come_back_tallest_first(client):
    """A truncated response must lose the buildings that matter least."""
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    payload = client.get(
        "/api/buildings",
        params={"bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}"},
    ).json()

    tops = [b["height_m"] + b["base_m"] for b in payload["buildings"]]
    assert tops == sorted(tops, reverse=True)


def test_buildings_report_when_they_were_cut_off(client):
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    payload = client.get(
        "/api/buildings",
        params={
            "bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}",
            "max_features": 1,
        },
    ).json()

    assert len(payload["buildings"]) == 1
    assert payload["truncated"] is True


def test_a_bbox_with_nothing_in_it_is_not_an_error(client):
    payload = client.get("/api/buildings", params={"bbox": "10,10,10.1,10.1"}).json()
    assert payload == {"buildings": [], "truncated": False}


def test_amenities_are_served_from_the_index_not_the_parquet(client):
    """The map asks for these on every pan, so they must not re-read a file."""
    from shadeway.api import _state

    state = _state()
    lon, lat = state.graph.node_lonlat[0]
    response = client.get(
        "/api/amenities",
        params={"bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}"},
    )
    assert response.status_code == 200
    for record in response.json():
        assert set(record) == {"amenity_id", "kind", "name", "lat", "lon"}
    assert len(state.amenities) >= len(response.json())


def test_timeseries_window_defaults_to_the_walk_itself(client):
    """Backwards-compatible default: zero hours means the walk's own duration."""
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    route = parsed.routes[parsed.chosen_route_id]
    series = TimeseriesResponse.model_validate(
        client.get(
            f"/api/route/{parsed.chosen_route_id}/timeseries",
            params={"depart_iso": "2025-07-22T15:00:00-04:00", "step_minutes": 5},
        ).json()
    )
    span_minutes = (
        series.points[-1].at_iso - series.points[0].at_iso
    ).total_seconds() / 60.0
    assert span_minutes <= route.duration_s / 60.0 + 5.1


def test_timeseries_can_span_a_whole_afternoon(client):
    """The window the client asks for. Without it the series covers only the
    walk's own length, which answers a much smaller question."""
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    series = TimeseriesResponse.model_validate(
        client.get(
            f"/api/route/{parsed.chosen_route_id}/timeseries",
            params={
                "depart_iso": "2025-07-22T15:00:00-04:00",
                "step_minutes": 15,
                "hours": 6,
            },
        ).json()
    )
    span_minutes = (
        series.points[-1].at_iso - series.points[0].at_iso
    ).total_seconds() / 60.0
    assert 5.5 * 60 <= span_minutes <= 6 * 60
    assert len(series.points) >= 20


def test_timeseries_sun_fraction_falls_as_the_afternoon_goes_on(client):
    """A sanity check on the physics rather than the plumbing: the same route,
    walked later, sees less direct beam as the sun drops."""
    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    series = TimeseriesResponse.model_validate(
        client.get(
            f"/api/route/{parsed.chosen_route_id}/timeseries",
            params={
                "depart_iso": "2025-07-22T15:00:00-04:00",
                "step_minutes": 30,
                "hours": 6,
            },
        ).json()
    )
    assert series.points[-1].sun_fraction <= series.points[0].sun_fraction


def test_timeseries_uses_each_hour_own_weather(client, monkeypatch):
    """A cost model carries the weather it was built with and takes only the sun
    from the timestamp. Building one model for a six-hour window therefore walks
    the 9pm route through 3pm's air temperature — which flattens exactly the
    curve this endpoint exists to show."""
    from shadeway.api import _state

    state = _state()
    real = state.weather.at
    asked: list[int] = []

    def recording(lat, lon, when):
        asked.append(when.hour)
        snapshot = real(lat, lon, when)
        # cool by one degree per hour, so a frozen model is visible in the output
        return snapshot.model_copy(
            update={"air_temp_c": 40.0 - when.hour, "observed_iso": when}
        )

    monkeypatch.setattr(state.weather, "at", recording)

    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    asked.clear()
    series = TimeseriesResponse.model_validate(
        client.get(
            f"/api/route/{parsed.chosen_route_id}/timeseries",
            params={
                "depart_iso": "2025-07-22T15:00:00-04:00",
                "step_minutes": 30,
                "hours": 5,
            },
        ).json()
    )

    assert len(set(asked)) >= 5, f"weather was only asked for hours {sorted(set(asked))}"
    # falling air temperature must show up as a falling felt temperature
    assert series.points[-1].mean_feels_like_c < series.points[0].mean_feels_like_c


def test_timeseries_builds_one_model_per_hour_not_per_step(client, monkeypatch):
    """The fix must not turn a cheap endpoint into an expensive one."""
    from shadeway.api import _state

    state = _state()
    real = state.weather.at
    calls: list[int] = []

    def counting(lat, lon, when):
        calls.append(when.hour)
        return real(lat, lon, when)

    monkeypatch.setattr(state.weather, "at", counting)

    parsed = RouteResponse.model_validate(
        client.post("/api/route", json=_body(client)).json()
    )
    calls.clear()
    client.get(
        f"/api/route/{parsed.chosen_route_id}/timeseries",
        params={
            "depart_iso": "2025-07-22T15:00:00-04:00",
            "step_minutes": 15,
            "hours": 4,
        },
    )
    # 17 steps across 5 distinct hours
    assert len(calls) <= 6, f"{len(calls)} weather lookups for 5 hours"
