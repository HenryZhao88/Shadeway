"""Small, policy-conscious Nominatim client for explicit place searches.

Nominatim is deliberately kept behind our API: the browser never exposes the
provider to a burst of per-keystroke requests, and repeated demo searches are
served from a bounded in-memory cache.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MANHATTAN_VIEWBOX = "-74.0250,40.6980,-73.9060,40.8830"
ATTRIBUTION = "© OpenStreetMap contributors"
DEFAULT_USER_AGENT = (
    "shadeway/0.0.1 (+https://github.com/HenryZhao88/Shadeway)"
)


class GeocoderUnavailable(RuntimeError):
    """The upstream search service could not answer safely."""


class Geocoder:
    def __init__(
        self,
        *,
        url: str | None = None,
        user_agent: str | None = None,
        ttl_s: float = 86_400.0,
        max_entries: int = 256,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url = url or os.environ.get("SHADEWAY_GEOCODER_URL", NOMINATIM_URL)
        self.user_agent = user_agent or os.environ.get(
            "SHADEWAY_GEOCODER_USER_AGENT", DEFAULT_USER_AGENT
        )
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._cache: "OrderedDict[str, tuple[float, list[dict[str, object]]]]" = (
            OrderedDict()
        )
        self._last_request_at: float | None = None
        self._lock = threading.Lock()

    def search(self, query: str) -> list[dict[str, object]]:
        clean = " ".join(query.split())
        key = clean.casefold()
        with self._lock:
            now = self._clock()
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.ttl_s:
                self._cache.move_to_end(key)
                return [dict(item) for item in cached[1]]
            if cached:
                self._cache.pop(key, None)

            if self._last_request_at is not None:
                wait = self.min_interval_s - (now - self._last_request_at)
                if wait > 0:
                    self._sleep(wait)
            self._last_request_at = self._clock()

            try:
                response = httpx.get(
                    self.url,
                    params={
                        "q": clean,
                        "format": "jsonv2",
                        "addressdetails": 1,
                        "countrycodes": "us",
                        "viewbox": MANHATTAN_VIEWBOX,
                        "bounded": 1,
                        "limit": 5,
                    },
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept-Language": "en",
                    },
                    timeout=8.0,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("unexpected geocoder response")
                results = self._parse(payload)
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise GeocoderUnavailable("place search is temporarily unavailable") from exc

            self._cache[key] = (self._clock(), results)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
            return [dict(item) for item in results]

    @staticmethod
    def _parse(payload: list[Any]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            label = item.get("display_name")
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not isinstance(label, str) or not label.strip():
                continue
            kind = item.get("addresstype") or item.get("type") or "place"
            results.append(
                {
                    "label": label.strip(),
                    "lat": lat,
                    "lon": lon,
                    "kind": str(kind).replace("_", " "),
                }
            )
        return results
