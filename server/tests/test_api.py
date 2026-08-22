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
