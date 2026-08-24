import pytest
from fastapi.testclient import TestClient

from shadeway.stub_api import app
from shadeway_contracts.api import (
    DepartureCurveResponse,
    RouteResponse,
    TimeseriesResponse,
)
from shadeway_contracts.fixtures import FIXTURE_DEST, FIXTURE_ORIGIN


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_route_returns_a_valid_route_response(client):
    body = client.post(
        "/api/route",
        json={
            "origin": FIXTURE_ORIGIN.model_dump(),
            "destination": FIXTURE_DEST.model_dump(),
            "depart_iso": "2025-07-22T15:00:00-04:00",
        },
    )
    assert body.status_code == 200
    parsed = RouteResponse.model_validate(body.json())
    assert parsed.chosen_route_id in parsed.routes
    assert parsed.routes["fastest"].feels_like_c.mean_c > (
        parsed.routes["shadeway"].feels_like_c.mean_c
    )


def test_route_rejects_a_naive_departure_time(client):
    body = client.post(
        "/api/route",
        json={
            "origin": FIXTURE_ORIGIN.model_dump(),
            "destination": FIXTURE_DEST.model_dump(),
            "depart_iso": "2025-07-22T15:00:00",
        },
    )
    assert body.status_code == 422


def test_timeseries_covers_the_whole_walk(client):
    body = client.get(
        "/api/route/shadeway/timeseries",
        params={"depart_iso": "2025-07-22T15:00:00-04:00", "step_minutes": 5},
    )
    parsed = TimeseriesResponse.model_validate(body.json())
    assert len(parsed.points) >= 4
    assert parsed.route_id == "shadeway"


def test_departure_curve_marks_now_and_best(client):
    body = client.get(
        "/api/departure-curve",
        params={
            "origin_lat": FIXTURE_ORIGIN.lat, "origin_lon": FIXTURE_ORIGIN.lon,
            "dest_lat": FIXTURE_DEST.lat, "dest_lon": FIXTURE_DEST.lon,
            "from_iso": "2025-07-22T15:00:00-04:00", "hours": 4,
        },
    )
    parsed = DepartureCurveResponse.model_validate(body.json())
    assert len(parsed.points) == 16  # 4 hours at 15-minute steps
    assert parsed.now_index == 0
    best = min(range(len(parsed.points)),
               key=lambda i: parsed.points[i].best_mean_feels_like_c)
    assert parsed.best_index == best


def test_cors_allows_the_vite_dev_server(client):
    resp = client.options(
        "/api/route",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_stub_serves_buildings_so_the_client_can_cast_shadows():
    """`make stub` + `make dev` is the documented no-download path. A client
    with no footprints opens on a city with no shade in it, which is the one
    thing the first five seconds of the demo is about."""
    from fastapi.testclient import TestClient

    from shadeway.stub_api import app

    client = TestClient(app)
    response = client.get("/api/buildings", params={"bbox": "-180,-90,180,90"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["buildings"], "the fixture city has no prisms in it"
    for building in payload["buildings"]:
        assert building["height_m"] > 0
        assert len(building["polygon"]) >= 3
        for lon, lat in building["polygon"]:
            assert -180 <= lon <= 180 and -90 <= lat <= 90


def test_stub_buildings_respect_the_bbox():
    from fastapi.testclient import TestClient

    from shadeway.stub_api import app

    client = TestClient(app)
    empty = client.get("/api/buildings", params={"bbox": "10,10,11,11"}).json()
    assert empty["buildings"] == []
