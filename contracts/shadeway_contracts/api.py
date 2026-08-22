"""The frozen REST contract. Track B implements it, Track C consumes it.

Everything crossing this boundary is WGS84 lon/lat and °C. No projected metres,
no percentages, no kilojoules.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LatLon(Frozen):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class HeatProfile(Frozen):
    """Collapses age / medical sensitivity / outdoor work / pace into one number:
    how many extra walking minutes one degree of cooling is worth."""

    name: str
    minutes_per_degree: float = Field(ge=0, le=30)


PRESET_PROFILES: dict[str, HeatProfile] = {
    "standard": HeatProfile(name="standard", minutes_per_degree=1.0),
    "sensitive": HeatProfile(name="sensitive", minutes_per_degree=3.0),
    "high_risk": HeatProfile(name="high risk", minutes_per_degree=6.0),
}


class RouteRequest(Frozen):
    origin: LatLon
    destination: LatLon
    depart_iso: AwareDatetime
    profile: HeatProfile = PRESET_PROFILES["standard"]
    walk_speed_ms: float = Field(default=1.35, gt=0.3, le=3.0)
    max_alternatives: int = Field(default=3, ge=1, le=8)
    time_dependent: bool = True


class WeatherSnapshot(Frozen):
    observed_iso: AwareDatetime
    air_temp_c: float
    relative_humidity_pct: float
    wind_speed_10m_ms: float
    cloud_cover_pct: float
    direct_normal_wm2: float
    diffuse_wm2: float
    global_horizontal_wm2: float
    uv_index: float
    source: str = "open-meteo"


class FeelsLike(Frozen):
    mean_c: float
    max_c: float
    p90_c: float


class Exposure(Frozen):
    sun_fraction: float = Field(ge=0, le=1)
    mean_svf: float = Field(ge=0, le=1)
    canopy_fraction: float = Field(ge=0, le=1)


class LegStep(Frozen):
    """One graph edge as walked, with the sun where it actually was at that moment."""

    edge_id: int
    street_name: str
    side: int  # tables.Side
    kind: int  # tables.EdgeKind
    geometry: list[tuple[float, float]]  # [[lon, lat], ...]
    length_m: float
    enter_iso: AwareDatetime
    exit_iso: AwareDatetime
    feels_like_c: float
    tmrt_c: float
    f_sun: float = Field(ge=0, le=1)
    svf: float = Field(ge=0, le=1)


class InstructionWhy(Frozen):
    """The evidence line under a turn card. Optional fields stay None when unknown."""

    sunlit_until_iso: AwareDatetime | None = None
    shaded_by: str | None = None  # "500 Fifth Ave", "honey locust canopy"
    delta_c: float | None = None
    dappled: bool = False  # true when the shade is high-tau canopy, not opaque


class Instruction(Frozen):
    type: str  # "start" | "continue" | "turn" | "cross" | "rest" | "arrive"
    at: LatLon
    text: str
    why: InstructionWhy | None = None


class WaypointSuggestion(Frozen):
    amenity_id: int
    kind: int  # tables.AmenityKind
    name: str
    at: LatLon
    detour_s: float
    inserted_after_leg: int


class Route(Frozen):
    route_id: str
    label: str  # "fastest" | "shadeway" | "alternative 2" ...
    depart_iso: AwareDatetime
    arrive_iso: AwareDatetime
    duration_s: float
    distance_m: float
    feels_like_c: FeelsLike
    exposure: Exposure
    legs: list[LegStep]
    instructions: list[Instruction]
    waypoints: list[WaypointSuggestion] = []


class FrontierPoint(Frozen):
    """One point on the pareto frontier. The heat-profile slider selects among these
    without re-running any search."""

    route_id: str
    duration_s: float
    mean_feels_like_c: float


class RouteResponse(Frozen):
    request_id: str
    computed_at: AwareDatetime
    weather: WeatherSnapshot
    frontier: list[FrontierPoint]
    routes: dict[str, Route]
    chosen_route_id: str
    cache_warm: bool = True
    compute_ms: float = 0.0


class TimeseriesPoint(Frozen):
    at_iso: AwareDatetime
    mean_feels_like_c: float
    max_feels_like_c: float
    sun_fraction: float


class TimeseriesResponse(Frozen):
    """The heat-vs-time curve for one already-displayed route. One call, whole series."""

    route_id: str
    points: list[TimeseriesPoint]


class DeparturePoint(Frozen):
    depart_iso: AwareDatetime
    best_mean_feels_like_c: float
    best_duration_s: float


class DepartureCurveResponse(Frozen):
    points: list[DeparturePoint]
    now_index: int
    best_index: int


class PlantRequest(Frozen):
    positions: list[LatLon]
    species: str
    dbh_cm: float = 20.0


class PlantResponse(Frozen):
    planted: int
    invalidated_samples: int
    scene_version: int


ISO = datetime  # re-export convenience for downstream annotations
