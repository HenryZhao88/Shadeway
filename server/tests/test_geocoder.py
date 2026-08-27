import httpx
import pytest

from shadeway.geocoder import MANHATTAN_VIEWBOX, Geocoder, GeocoderUnavailable


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_search_uses_a_bounded_manhattan_query_and_identifying_agent(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers, timeout))
        return FakeResponse(
            [
                {
                    "display_name": "Bryant Park, Manhattan, New York, NY",
                    "lat": "40.7536",
                    "lon": "-73.9840",
                    "addresstype": "park",
                }
            ]
        )

    monkeypatch.setattr("shadeway.geocoder.httpx.get", fake_get)
    result = Geocoder(min_interval_s=0).search("  Bryant   Park ")

    assert result == [
        {
            "label": "Bryant Park, Manhattan, New York, NY",
            "lat": 40.7536,
            "lon": -73.984,
            "kind": "park",
        }
    ]
    _, params, headers, timeout = calls[0]
    assert params["q"] == "Bryant Park"
    assert params["bounded"] == 1
    assert params["viewbox"] == MANHATTAN_VIEWBOX
    assert params["limit"] == 5
    assert "Shadeway" in headers["User-Agent"]
    assert timeout == 8.0


def test_repeated_normalized_search_is_served_from_cache(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse([])

    monkeypatch.setattr("shadeway.geocoder.httpx.get", fake_get)
    client = Geocoder(min_interval_s=0)
    client.search("Times Square")
    client.search("  times   square  ")
    assert len(calls) == 1


def test_distinct_upstream_requests_are_spaced_one_second_apart(monkeypatch):
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(
        "shadeway.geocoder.httpx.get", lambda *args, **kwargs: FakeResponse([])
    )
    client = Geocoder(clock=lambda: now[0], sleep=sleep)
    client.search("Bryant Park")
    client.search("Grand Central")
    assert sleeps == [1.0]


def test_network_errors_become_a_stable_service_error(monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("shadeway.geocoder.httpx.get", offline)
    with pytest.raises(GeocoderUnavailable, match="temporarily unavailable"):
        Geocoder(min_interval_s=0).search("Bryant Park")
