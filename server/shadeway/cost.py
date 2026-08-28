"""The bridge between physics and routing.

The router receives `EdgeCostModel.traverse` as a callable and never learns what
is behind it. That is the whole coupling, and keeping it that thin is what makes
both sides testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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

    def prefetch(self, edge_ids: np.ndarray, minute_keys: np.ndarray) -> None:
        """Vectorise all feasible ``(edge, minute)`` thermal costs.

        A route search used to invoke several small NumPy kernels for every
        edge relaxation. Most sidewalk edges carry only a handful of samples,
        so dispatching those kernels thousands of times cost far more than the
        arithmetic itself on small hosting CPUs. The router already knows its
        exact time corridor; this method evaluates that corridor in one batch
        per solar minute and fills the same cache consumed by ``traverse``.

        This is purely a scheduling optimisation. Cache keys, minute-level sun
        precision, sample-level physics, and returned ``EdgeCost`` values are
        identical to the scalar path.
        """
        edges = np.asarray(edge_ids, dtype=np.int64)
        minutes = np.asarray(minute_keys, dtype=np.int64)
        if not len(edges):
            return
        if edges.shape != minutes.shape:
            raise ValueError("edge_ids and minute_keys must have the same shape")

        missing = np.fromiter(
            (
                (int(edge_id), int(minute)) not in self._cost_cache
                for edge_id, minute in zip(edges, minutes)
            ),
            dtype=bool,
            count=len(edges),
        )
        if not missing.any():
            return
        edges = edges[missing]
        minutes = minutes[missing]
        order = np.argsort(minutes, kind="stable")
        edges = edges[order]
        minutes = minutes[order]
        boundaries = np.flatnonzero(np.r_[True, minutes[1:] != minutes[:-1], True])
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            self._prefetch_minute(edges[start:stop], int(minutes[start]))

    def _prefetch_minute(self, edges: np.ndarray, minute_key: int) -> None:
        graph = self.graph
        counts = graph.sample_count[edges].astype(np.int64, copy=False)
        if np.any(counts <= 0):
            # Built city edges always have samples. Preserve the scalar
            # behaviour for experimental graphs rather than inventing a mean
            # over an empty edge.
            when = datetime.fromtimestamp(minute_key * 60, tz=UTC)
            for edge_id in edges:
                key = (int(edge_id), minute_key)
                self._cost_cache.setdefault(key, self._compute(int(edge_id), when))
            return

        offsets = np.cumsum(counts) - counts
        repeated_offsets = np.repeat(offsets, counts)
        sample_ids = (
            np.repeat(graph.sample_start[edges], counts)
            + np.arange(int(counts.sum()), dtype=np.int64)
            - repeated_offsets
        )
        when = datetime.fromtimestamp(minute_key * 60, tz=UTC)
        azimuth, elevation = self._sun(when)
        f_sun = self.horizon.f_sun(sample_ids, azimuth, elevation)
        svf = self.horizon.svf(sample_ids)
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
            radiation, f_sun, svf, self.sample_albedo[sample_ids]
        )
        feels_like = self.utci_table.lookup(tmrt_values)

        def means(values) -> np.ndarray:
            return np.add.reduceat(np.asarray(values), offsets) / counts

        mean_feels = means(feels_like)
        mean_f_sun = means(f_sun)
        mean_svf = means(svf)
        mean_tmrt = means(tmrt_values)
        mean_canopy = means((f_sun > 0.0) & (f_sun < 1.0))
        durations = self.edge_durations()[edges]
        for index, edge_id in enumerate(edges):
            duration_s = float(durations[index])
            feels = float(mean_feels[index])
            self._cost_cache[(int(edge_id), minute_key)] = EdgeCost(
                duration_s=duration_s,
                heat_degree_minutes=feels * (duration_s / 60.0),
                mean_feels_like_c=feels,
                mean_f_sun=float(mean_f_sun[index]),
                mean_svf=float(mean_svf[index]),
                mean_tmrt_c=float(mean_tmrt[index]),
                mean_canopy_fraction=float(mean_canopy[index]),
            )

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
