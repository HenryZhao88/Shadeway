from datetime import datetime, timedelta, timezone

import pytest

from shadeway.weather import FALLBACK_SNAPSHOT, WeatherClient

EDT = timezone(timedelta(hours=-4))
WHEN = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)

FAKE_PAYLOAD = {
    "hourly": {
        "time": ["2025-07-22T18:00", "2025-07-22T19:00"],
        "temperature_2m": [30.6, 30.1],
        "relative_humidity_2m": [48, 51],
        "wind_speed_10m": [12.2, 11.0],
        "cloud_cover": [6, 10],
        "direct_normal_irradiance": [799, 690],
        "diffuse_radiation": [148, 141],
        "shortwave_radiation": [712, 640],
        "uv_index": [8.0, 6.4],
    }
}


@pytest.fixture()
def client(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return FAKE_PAYLOAD

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return FakeResponse()

    monkeypatch.setattr("shadeway.weather.httpx.get", fake_get)
    c = WeatherClient()
    c._calls = calls
    return c


def test_maps_open_meteo_fields_onto_the_contract(client):
    snapshot = client.at(40.758, -73.985, WHEN)
    assert snapshot.air_temp_c == 30.6
    assert snapshot.direct_normal_wm2 == 799.0
    assert snapshot.diffuse_wm2 == 148.0
    assert snapshot.global_horizontal_wm2 == 712.0
    assert snapshot.cloud_cover_pct == 6.0
    assert snapshot.source == "open-meteo"


def test_wind_is_converted_from_kmh_to_ms(client):
    snapshot = client.at(40.758, -73.985, WHEN)
    assert abs(snapshot.wind_speed_10m_ms - 12.2 / 3.6) < 1e-6


def test_second_call_within_ttl_does_not_refetch(client):
    client.at(40.758, -73.985, WHEN)
    client.at(40.758, -73.985, WHEN + timedelta(minutes=5))
    assert len(client._calls) == 1


def test_a_distant_location_is_a_separate_cache_entry(client):
    client.at(40.758, -73.985, WHEN)
    client.at(40.650, -73.950, WHEN)
    assert len(client._calls) == 2


def test_network_failure_degrades_to_the_fallback_instead_of_500ing(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network on the conference wifi")

    monkeypatch.setattr("shadeway.weather.httpx.get", boom)
    snapshot = WeatherClient().at(40.758, -73.985, WHEN)
    assert snapshot.source.startswith("fallback")
    assert snapshot.air_temp_c == FALLBACK_SNAPSHOT.air_temp_c
