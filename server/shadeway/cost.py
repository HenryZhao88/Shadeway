"""The bridge between physics and routing.

The router receives `EdgeCostModel.traverse` as a callable and never learns what
is behind it. That is the whole coupling, and keeping it that thin is what makes
both sides testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from shadeway.horizon import HorizonCache
from shadeway.thermal import tmrt as tmrt_mod
from shadeway.thermal.solar import sun_position
from shadeway.thermal.utci import UtciTable
from shadeway_contracts.api import WeatherSnapshot

CROSSING_PENALTY_S = 20.0  # signal wait + curb; tune once you see real routes


def canopy_fraction(f_sun: np.ndarray) -> float:
    """Share of samples with a transmissive, rather than binary, direct beam."""
    values = np.asarray(f_sun)
    return float(np.mean((values > 0.0) & (values < 1.0))) if len(values) else 0.0


@dataclass(frozen=True)
class EdgeCost:
    duration_s: float
    heat_degree_minutes: float
    mean_feels_like_c: float
    mean_f_sun: float
    mean_svf: float
    mean_tmrt_c: float
    # Fraction of sample points under transmissive canopy. This must be
    # classified before f_sun is averaged: an edge that is half open and half
    # behind a building also has mean_f_sun=0.5, but contains no canopy.
    mean_canopy_fraction: float = 0.0


class EdgeCostModel:
    def __init__(
        self,
        horizon: HorizonCache,
        weather: WeatherSnapshot,
        sample_albedo: np.ndarray,
        lat: float,
        lon: float,
        walk_speed_ms: float = 1.35,
        crossing_penalty_s: float = CROSSING_PENALTY_S,
    ) -> None:
        self.horizon = horizon
        self.weather = weather
        self.sample_albedo = sample_albedo
        self.lat = lat
        self.lon = lon
        self.walk_speed_ms = walk_speed_ms
        self.crossing_penalty_s = crossing_penalty_s
        # one UTCI curve for this hour's weather; the hot path is a lerp
        self.utci_table = UtciTable.build(
            air_temp_c=weather.air_temp_c,
            wind_10m_ms=weather.wind_speed_10m_ms,
            relative_humidity_pct=weather.relative_humidity_pct,
        )
        self._sun_cache: dict[int, tuple[float, float]] = {}
        self._cost_cache: dict[tuple[int, int], EdgeCost] = {}
        self._durations: np.ndarray | None = None
        self.graph = None

    def bind_graph(self, graph) -> None:
        """Called once by the router so traverse() can read edge attributes."""
        if graph is not self.graph:
            self._cost_cache.clear()
            self._durations = None
        self.graph = graph

    def edge_durations(self) -> np.ndarray:
        """Walk time for every edge, as a single array.

        Walk time does not depend on the time of day — only length, speed and
        the crossing penalty. That is what lets the router bound its search on
        the time axis before running a single ray cast.
        """
        if self._durations is None:
            graph = self.graph
            durations = (
                graph.edge_length_m.astype(np.float64) / self.walk_speed_ms
            )
            durations += (graph.edge_kind == 1) * self.crossing_penalty_s
            self._durations = durations
        return self._durations

    def _sun(self, when: datetime) -> tuple[float, float]:
        """Sun position, cached to the minute. The sun does not move meaningfully
        inside one minute, and this is called thousands of times per search."""
        key = int(when.timestamp() // 60)
        if key not in self._sun_cache:
            # The cache key defines the precision, so the calculation must use
            # the same canonical instant. Otherwise whichever edge first asks
            # about a minute determines the result for every later caller.
            minute = when.replace(second=0, microsecond=0)
            position = sun_position(minute, self.lat, self.lon)
            self._sun_cache[key] = (position.azimuth_deg, position.elevation_deg)
        return self._sun_cache[key]

    def traverse(self, edge_id: int, enter_at: datetime) -> EdgeCost:
        """Memoised on (edge, minute).

        The label-setting search relaxes the same edge from many labels with
        arrival times seconds apart, and the sun position it feeds on is
        already quantised to the minute by `_sun` — so every one of those calls
        was recomputing an identical answer. Caching it changes no number and
        takes the search from minutes to well under a second on Manhattan.
        """
        key = (int(edge_id), int(enter_at.timestamp() // 60))
        hit = self._cost_cache.get(key)
        if hit is None:
            hit = self._compute(int(edge_id), enter_at)
            self._cost_cache[key] = hit
        return hit

    def _compute(self, edge_id: int, enter_at: datetime) -> EdgeCost:
        graph = self.graph
        length_m = float(graph.edge_length_m[edge_id])
        duration_s = length_m / self.walk_speed_ms
        if graph.edge_kind[edge_id] == 1:  # EdgeKind.CROSSING
            duration_s += self.crossing_penalty_s

        ids = graph.sample_ids(edge_id)
        azimuth, elevation = self._sun(enter_at)
        f_sun = self.horizon.f_sun(ids, azimuth, elevation)
        svf = self.horizon.svf(ids)

        radiation = tmrt_mod.RadiationInputs(
            direct_normal_wm2=self.weather.direct_normal_wm2,
            diffuse_wm2=self.weather.diffuse_wm2,
            global_horizontal_wm2=self.weather.global_horizontal_wm2,
            air_temp_c=self.weather.air_temp_c,
            relative_humidity_pct=self.weather.relative_humidity_pct,
            cloud_cover_pct=self.weather.cloud_cover_pct,
            solar_elevation_deg=elevation,
        )
        tmrt_values = tmrt_mod.tmrt_c_vec(
            radiation, f_sun, svf, self.sample_albedo[ids]
        )
        feels_like = self.utci_table.lookup(tmrt_values)

        mean_feels_like = float(np.mean(feels_like))
        return EdgeCost(
            duration_s=duration_s,
            heat_degree_minutes=mean_feels_like * (duration_s / 60.0),
            mean_feels_like_c=mean_feels_like,
            mean_f_sun=float(np.mean(f_sun)),
            mean_svf=float(np.mean(svf)),
            mean_tmrt_c=float(np.mean(tmrt_values)),
            mean_canopy_fraction=canopy_fraction(f_sun),
        )
