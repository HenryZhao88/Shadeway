from datetime import datetime, timedelta, timezone

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


def test_route_returns_a_contract_valid_response(client):
    response = client.post("/api/route", json=_body(client))
    assert response.status_code == 200
    parsed = RouteResponse.model_validate(response.json())
    assert parsed.routes
    assert parsed.chosen_route_id in parsed.routes


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
        params={"depart_iso": "2025-07-22T15:00:00-04:00", "step_minutes": 5},
    )
    series = TimeseriesResponse.model_validate(response.json())
    assert len(series.points) >= 2


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
