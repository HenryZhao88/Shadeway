"""Open-Meteo client. Keyless, CORS-open, cached server-side.

Deliberately NOT under thermal/ — that package is pure and this does network IO.

The CORS-open property matters beyond politeness: if the server dies during the
demo, the browser can call Open-Meteo directly. Don't add a proxy that breaks it.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx

from shadeway_contracts.api import WeatherSnapshot

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "direct_normal_irradiance",
    "diffuse_radiation",
    "shortwave_radiation",
    "uv_index",
]

# A hot NYC summer afternoon. Used only when the network is unreachable, and
# always labelled as such so we never silently present made-up weather as real.
FALLBACK_SNAPSHOT = WeatherSnapshot(
    observed_iso=datetime(2025, 7, 22, 15, 0, tzinfo=timezone(timedelta(hours=-4))),
    air_temp_c=32.0,
    relative_humidity_pct=45.0,
    wind_speed_10m_ms=3.0,
    cloud_cover_pct=10.0,
    direct_normal_wm2=800.0,
    diffuse_wm2=150.0,
    global_horizontal_wm2=700.0,
    uv_index=8.0,
    source="fallback (network unavailable)",
)

KMH_TO_MS = 1.0 / 3.6  # open-meteo's default wind unit is km/h
GRID_DEG = 0.05  # ~5 km: one cache entry per neighbourhood, not per coordinate


class WeatherClient:
    def __init__(self, ttl_s: float = 900.0) -> None:
        self.ttl_s = ttl_s
        self._cache: dict[tuple[float, float], tuple[float, dict]] = {}

    def _key(self, lat: float, lon: float) -> tuple[float, float]:
        return (round(lat / GRID_DEG), round(lon / GRID_DEG))

    def _payload(self, lat: float, lon: float) -> dict | None:
        key = self._key(lat, lon)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl_s:
            return hit[1]
        try:
            response = httpx.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "timezone": "America/New_York",
                    "forecast_days": 2,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        self._cache[key] = (time.time(), payload)
        return payload

    def at(self, lat: float, lon: float, when: datetime) -> WeatherSnapshot:
        payload = self._payload(lat, lon)
        if payload is None:
            return FALLBACK_SNAPSHOT.model_copy(update={"observed_iso": when})
        return self._nearest(payload, when)

    def series(
        self, lat: float, lon: float, start: datetime, hours: int
    ) -> list[WeatherSnapshot]:
        return [self.at(lat, lon, start + timedelta(hours=h)) for h in range(hours)]

    def _nearest(self, payload: dict, when: datetime) -> WeatherSnapshot:
        hourly = payload["hourly"]
        stamps = [datetime.fromisoformat(t) for t in hourly["time"]]
        target = when.replace(tzinfo=None)
        index = min(range(len(stamps)), key=lambda i: abs(stamps[i] - target))
        return WeatherSnapshot(
            observed_iso=when,
            air_temp_c=float(hourly["temperature_2m"][index]),
            relative_humidity_pct=float(hourly["relative_humidity_2m"][index]),
            wind_speed_10m_ms=float(hourly["wind_speed_10m"][index]) * KMH_TO_MS,
            cloud_cover_pct=float(hourly["cloud_cover"][index]),
            direct_normal_wm2=float(hourly["direct_normal_irradiance"][index]),
            diffuse_wm2=float(hourly["diffuse_radiation"][index]),
            global_horizontal_wm2=float(hourly["shortwave_radiation"][index]),
            uv_index=float(hourly["uv_index"][index]),
            source="open-meteo",
        )
