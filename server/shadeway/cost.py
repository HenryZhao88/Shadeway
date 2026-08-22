"""The bridge between physics and routing.

The router receives `EdgeCostModel.traverse` as a callable and never learns what
is behind it. That is the whole coupling, and keeping it that thin is what makes
both sides testable in isolation.

The full EdgeCostModel (horizon cache + Tmrt + UTCI) lands with the thermal
tasks; for now this module defines the cost vocabulary the router speaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

CROSSING_PENALTY_S = 20.0  # signal wait + curb; tune once you see real routes


@dataclass(frozen=True)
class EdgeCost:
    duration_s: float
    heat_degree_minutes: float
    mean_feels_like_c: float
    mean_f_sun: float
    mean_svf: float
    mean_tmrt_c: float


class EdgeCostModel:
    """Placeholder until the thermal tasks arrive; keeps the interface stable."""

    def __init__(
        self,
        weather,
        sample_albedo: np.ndarray,
        lat: float,
        lon: float,
        walk_speed_ms: float = 1.35,
        crossing_penalty_s: float = CROSSING_PENALTY_S,
    ) -> None:
        self.weather = weather
        self.sample_albedo = sample_albedo
        self.lat = lat
        self.lon = lon
        self.walk_speed_ms = walk_speed_ms
        self.crossing_penalty_s = crossing_penalty_s

    def bind_graph(self, graph) -> None:
        self.graph = graph

    def traverse(self, edge_id: int, enter_at: datetime) -> EdgeCost:
        raise NotImplementedError("arrives with the thermal tasks (plan 02, tasks 5-8)")
