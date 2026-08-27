"""The real API. Serves the same paths and shapes as stub_api, backed by physics."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import shapely
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pyproj import Transformer
from starlette.middleware.gzip import GZipMiddleware

from shadeway import instructions as instr
from shadeway import waypoints as waypoints_mod
from shadeway.cost import EdgeCostModel
from shadeway.evidence import EvidenceProvider
from shadeway.geocoder import ATTRIBUTION, Geocoder, GeocoderUnavailable
from shadeway.horizon import FINGERPRINT_FILES, HorizonCache, source_fingerprint
from shadeway.router import timedep
from shadeway.router.graph import Graph
from shadeway.scene import Scene
from shadeway.weather import WeatherClient
from shadeway_contracts.api import (
    DepartureCurveResponse,
    DeparturePoint,
    Exposure,
    FeelsLike,
    FrontierPoint,
    LegStep,
    PlantRequest,
    PlantResponse,
    Route,
    RouteRequest,
    RouteResponse,
    TimeseriesPoint,
    TimeseriesResponse,
    WeatherSnapshot,
)
from shadeway_contracts.tables import CRS_EPSG

_to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)


class ReadWriteLock:
    """Concurrent scene reads with an exclusive lane for live scene edits."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read(self):
        with self._condition:
            while self._writer or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self):
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


@dataclass
class AppState:
    graph: Graph
    scene: Scene
    horizon: HorizonCache
    weather: WeatherClient
    data_dir: Path
    amenities: waypoints_mod.AmenityIndex
    # Scene edits and horizon invalidation are one transaction. Concurrent
    # readers remain safe and fast; a write waits for them and excludes new
    # reads until both the scene change and cache invalidation are complete.
    runtime_lock: ReadWriteLock = field(default_factory=ReadWriteLock)

    @classmethod
    def build(cls) -> "AppState":
        data_dir = Path(os.environ.get("SHADEWAY_DATA", "data/nyc"))
        if not (data_dir / "edges.parquet").exists():
            data_dir = Path("data/fixtures")
        graph = Graph.load(data_dir)
        scene = Scene.load(data_dir)
        horizon = HorizonCache(
            scene,
            graph.sample_xy,
            fingerprint=source_fingerprint(data_dir),
        )
        precomputed = data_dir / "horizon.npz"
        if precomputed.exists():
            # Original caches predate embedded fingerprints. They remain safe
            # only when they are newer than every parquet that affects shade;
            # all newly written caches use the exact hash instead.
            legacy_ok = precomputed.stat().st_mtime_ns >= max(
                (data_dir / name).stat().st_mtime_ns for name in FINGERPRINT_FILES
            )
            if horizon.load_precomputed(precomputed, legacy_ok=legacy_ok):
                print(f"loaded warm horizon cache from {precomputed}")
            else:
                print(f"horizon cache at {precomputed} did not match the scene; "
                      "serving cold (slow until warmed)")
        return cls(
            graph=graph,
            scene=scene,
            horizon=horizon,
            weather=WeatherClient(),
            data_dir=data_dir,
            amenities=waypoints_mod.AmenityIndex.load(data_dir),
        )


STATE: AppState | None = None


def _state() -> AppState:
    global STATE
    if STATE is None:
        STATE = AppState.build()
    return STATE


def _planting_enabled() -> bool:
    return os.environ.get("SHADEWAY_ENABLE_PLANTING", "0").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


app = FastAPI(title="shadeway")
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# (request_id, route_id) -> (route, edge ids, the request that produced it).
#
# Route ids are intentionally human labels ("fastest", "shadeway") and collide
# across requests. request_id is already part of RouteResponse, so it is the
# authoritative namespace. The optional legacy lookup in timeseries is kept for
# old callers, but the shipped client always supplies request_id.
_ROUTE_CACHE: "OrderedDict[tuple[str, str], tuple[Route, list[int], RouteRequest]]" = OrderedDict()
_ROUTE_CACHE_MAX = 64
_ROUTE_CACHE_LOCK = threading.RLock()
GEOCODER = Geocoder()


def _remember(
    request_id: str,
    route_id: str,
    route: Route,
    edges: list[int],
    request: RouteRequest,
) -> None:
    key = (request_id, route_id)
    with _ROUTE_CACHE_LOCK:
        _ROUTE_CACHE.pop(key, None)
        _ROUTE_CACHE[key] = (route, edges, request)
        while len(_ROUTE_CACHE) > _ROUTE_CACHE_MAX:
            _ROUTE_CACHE.popitem(last=False)


def _recalled(
    route_id: str, request_id: str | None
) -> tuple[Route, list[int], RouteRequest] | None:
    """Return the exact route when namespaced; latest-by-label for legacy callers."""
    with _ROUTE_CACHE_LOCK:
        if request_id is not None:
            cached = _ROUTE_CACHE.get((request_id, route_id))
            if cached is not None:
                _ROUTE_CACHE.move_to_end((request_id, route_id))
            return cached
        for key in reversed(_ROUTE_CACHE):
            if key[1] == route_id:
                return _ROUTE_CACHE[key]
    return None


@app.get("/api/health")
def health() -> dict[str, object]:
    state = _state()
    return {
        "status": "ok",
        "scene": str(state.data_dir),
        "cache_warm": bool(state.horizon.warm.all()),
        "warm_fraction": float(state.horizon.warm.mean()),
        "n_edges": int(len(state.graph.edge_u)),
        "n_samples": int(state.graph.n_samples),
        "scene_version": state.scene.version,
        "planting_enabled": _planting_enabled(),
    }


def _add_waypoints(route: Route, walk_speed_ms: float) -> Route:
    """The cool-waypoints post-pass. Deleting these four lines deletes the
    feature; nothing else in the file refers to it."""
    state = _state()
    suggestions = waypoints_mod.suggest(
        route, state.amenities, state.graph, walk_speed_ms=walk_speed_ms
    )
    if not suggestions:
        return route
    cards = waypoints_mod.rest_instructions(suggestions, route)
    instructions = list(route.instructions)
    # rest cards go in ahead of "Arrive", in walk order
    tail = 1 if instructions and instructions[-1].type == "arrive" else 0
    instructions[len(instructions) - tail : len(instructions) - tail] = cards
    return route.model_copy(
        update={"waypoints": suggestions, "instructions": instructions}
    )


def _cost_model(origin_lonlat, when: datetime, walk_speed_ms: float) -> EdgeCostModel:
    state = _state()
    weather = state.weather.at(origin_lonlat[1], origin_lonlat[0], when)
    model = EdgeCostModel(
        horizon=state.horizon,
        weather=weather,
        sample_albedo=state.graph.sample_albedo,
        lat=origin_lonlat[1],
        lon=origin_lonlat[0],
        walk_speed_ms=walk_speed_ms,
    )
    model.bind_graph(state.graph)
    return model


def _leg(edge_id: int, enter_at: datetime, cost) -> LegStep:
    graph = _state().graph
    coords = shapely.get_coordinates(graph.geometry(edge_id))
    lon, lat = _to_ll.transform(coords[:, 0], coords[:, 1])
    return LegStep(
        edge_id=int(edge_id),
        street_name=graph.street_names[edge_id],
        side=int(graph.edge_side[edge_id]),
        kind=int(graph.edge_kind[edge_id]),
        geometry=[(float(a), float(b)) for a, b in zip(lon, lat)],
        length_m=float(graph.edge_length_m[edge_id]),
        enter_iso=enter_at,
        exit_iso=enter_at + timedelta(seconds=cost.duration_s),
        feels_like_c=cost.mean_feels_like_c,
        tmrt_c=cost.mean_tmrt_c,
        f_sun=float(cost.mean_f_sun),
        svf=float(cost.mean_svf),
    )


def _evidence(origin_lonlat) -> EvidenceProvider:
    state = _state()
    return EvidenceProvider(
        state.graph, state.scene, state.horizon,
        lat=origin_lonlat[1], lon=origin_lonlat[0],
    )


def _to_route(
    path, route_id: str, label: str, depart: datetime, model, evidence=None
) -> Route:
    legs: list[LegStep] = []
    canopy_fractions: list[float] = []
    clock = depart
    for edge_id in path.edges:
        cost = model.traverse(edge_id, clock)
        legs.append(_leg(edge_id, clock, cost))
        canopy_fractions.append(cost.mean_canopy_fraction)
        clock += timedelta(seconds=cost.duration_s)

    feels = np.array([leg.feels_like_c for leg in legs], dtype=np.float64)
    weights = np.array([leg.length_m for leg in legs], dtype=np.float64)
    weights = weights / max(weights.sum(), 1e-9)
    f_sun_arr = np.array([leg.f_sun for leg in legs], dtype=np.float64)
    svf_arr = np.array([leg.svf for leg in legs], dtype=np.float64)
    canopy_arr = np.asarray(canopy_fractions, dtype=np.float64)
    return Route(
        route_id=route_id,
        label=label,
        depart_iso=depart,
        arrive_iso=clock,
        duration_s=(clock - depart).total_seconds(),
        distance_m=float(sum(leg.length_m for leg in legs)),
        feels_like_c=FeelsLike(
            mean_c=float(np.sum(feels * weights)),
            max_c=float(feels.max()),
            p90_c=float(np.percentile(feels, 90)),
        ),
        exposure=Exposure(
            sun_fraction=float(np.sum(f_sun_arr * weights)),
            mean_svf=float(np.sum(svf_arr * weights)),
            canopy_fraction=float(np.sum(canopy_arr * weights)),
        ),
        legs=legs,
        instructions=instr.build(_state().graph, path, legs, evidence),
    )


@app.post("/api/route", response_model=RouteResponse)
def route(request: RouteRequest) -> RouteResponse:
    state = _state()
    with state.runtime_lock.read():
        return _route_locked(request, state)


def _route_locked(request: RouteRequest, state: AppState) -> RouteResponse:
    started = time.perf_counter()
    graph = state.graph
    request_id = str(uuid.uuid4())
    if not graph.covers(request.origin.lon, request.origin.lat):
        raise HTTPException(422, "starting point is outside the loaded map area")
    if not graph.covers(request.destination.lon, request.destination.lat):
        raise HTTPException(422, "destination is outside the loaded map area")
    origin = graph.nearest_node(request.origin.lon, request.origin.lat)
    destination = graph.nearest_node(request.destination.lon, request.destination.lat)
    if origin == destination:
        raise HTTPException(400, "origin and destination resolve to the same node")

    model = _cost_model(
        (request.origin.lon, request.origin.lat), request.depart_iso,
        request.walk_speed_ms,
    )
    if request.time_dependent:
        paths = timedep.solve(graph, origin, destination, request.depart_iso, model)
    else:
        from shadeway.router import bicriteria

        paths = bicriteria.search(
            graph, origin, destination, request.depart_iso, model.traverse
        )
    if not paths:
        raise HTTPException(404, "no route found")

    paths = sorted(paths, key=lambda p: p.duration_s)[: request.max_alternatives]
    evidence = _evidence((request.origin.lon, request.origin.lat))
    routes: dict[str, Route] = {}
    frontier: list[FrontierPoint] = []
    for index, path in enumerate(paths):
        route_id = "fastest" if index == 0 else (
            "shadeway" if index == len(paths) - 1 else f"alt{index}"
        )
        built = _to_route(
            path, route_id, route_id, request.depart_iso, model, evidence
        )
        built = _add_waypoints(built, request.walk_speed_ms)
        routes[route_id] = built
        _remember(request_id, route_id, built, path.edges, request)
        frontier.append(
            FrontierPoint(
                route_id=route_id,
                duration_s=built.duration_s,
                mean_feels_like_c=built.feels_like_c.mean_c,
            )
        )

    # the heat profile picks a frontier point: how many extra minutes is a
    # degree worth? no re-route, just a different point on a curve we have.
    budget_s = request.profile.minutes_per_degree * 60.0
    baseline = frontier[0]
    chosen = min(
        frontier,
        key=lambda p: (p.duration_s - baseline.duration_s)
        - budget_s * (baseline.mean_feels_like_c - p.mean_feels_like_c),
    )

    return RouteResponse(
        request_id=request_id,
        computed_at=request.depart_iso,
        weather=model.weather,
        frontier=sorted(frontier, key=lambda p: p.duration_s),
        routes=routes,
        chosen_route_id=chosen.route_id,
        cache_warm=bool(state.horizon.warm.all()),
        compute_ms=(time.perf_counter() - started) * 1000.0,
    )


@app.get("/api/route/{route_id}/timeseries", response_model=TimeseriesResponse)
def timeseries(
    route_id: str,
    depart_iso: datetime,
    step_minutes: int = Query(default=5, ge=1, le=60),
    hours: float = Query(default=0.0, ge=0.0, le=12.0),
    walk_speed_ms: float | None = Query(default=None, gt=0.3, le=3.0),
    request_id: str | None = Query(default=None, min_length=1, max_length=64),
) -> TimeseriesResponse:
    state = _state()
    with state.runtime_lock.read():
        return _timeseries_locked(
            route_id,
            depart_iso,
            step_minutes,
            hours,
            walk_speed_ms,
            request_id,
        )


def _timeseries_locked(
    route_id: str,
    depart_iso: datetime,
    step_minutes: int,
    hours: float,
    walk_speed_ms: float | None,
    request_id: str | None,
) -> TimeseriesResponse:
    """The heat-vs-time curve. One call returns the whole series, because it is
    the same sample points evaluated at N different times and the horizon cache
    makes that almost free.

    `hours` sets the window. Zero — the default, kept so existing callers do not
    change — spans the walk's own duration, which answers only "what if I set
    off a few minutes later". Anything else spans that many hours, which is the
    question a reader actually has: this route is fine now, what about at five?

    Walk speed defaults to whatever the /route call that produced this route
    asked for, so a slow walker's curve is that walker's curve — pass
    walk_speed_ms only to override it."""
    cached = _recalled(route_id, request_id)
    if cached is None:
        raise HTTPException(404, "unknown route id — request /api/route first")
    built, edges, origin_request = cached
    lon, lat = built.legs[0].geometry[0]
    speed = walk_speed_ms if walk_speed_ms is not None else origin_request.walk_speed_ms

    # One cost model PER HOUR, not one for the whole window.
    #
    # A model carries the weather it was built with — air temperature, wind,
    # humidity and the three irradiance terms — and only the sun position is
    # taken from the timestamp passed to traverse(). So a single model moves the
    # sun across the window while holding the weather frozen at the departure
    # hour, and a 9pm walk gets modelled with 3pm's air temperature and 183 W/m2
    # of diffuse. Harmless over the fifteen minutes the old default spanned;
    # wrong over the six hours this endpoint now serves, and wrong in exactly
    # the direction that flattens the curve the reader came for.
    #
    # Weather is hourly at source and cached per neighbourhood, so keying these
    # by hour costs one UTCI table per hour and no extra network.
    models: dict[datetime, EdgeCostModel] = {}

    def model_at(when: datetime) -> EdgeCostModel:
        hour = when.replace(minute=0, second=0, microsecond=0)
        if hour not in models:
            models[hour] = _cost_model((lon, lat), hour, speed)
        return models[hour]

    window_minutes = hours * 60.0 if hours > 0 else built.duration_s / 60.0
    steps = max(2, int(window_minutes / step_minutes) + 1)
    points: list[TimeseriesPoint] = []
    lengths = np.asarray(
        [leg.length_m for leg in built.legs],
        dtype=np.float64,
    )
    weights = lengths / max(float(lengths.sum()), 1e-9)
    for i in range(steps):
        at = depart_iso + timedelta(minutes=i * step_minutes)
        # This is one whole walk beginning at `at`, not a snapshot where every
        # block is traversed simultaneously. Advance the clock edge by edge so
        # the sun moves during the walk, exactly as /route does.
        model = model_at(at)
        clock = at
        costs = []
        for edge_id in edges:
            cost = model.traverse(edge_id, clock)
            costs.append(cost)
            clock += timedelta(seconds=cost.duration_s)
        feels = np.asarray([c.mean_feels_like_c for c in costs], dtype=np.float64)
        points.append(
            TimeseriesPoint(
                at_iso=at,
                mean_feels_like_c=float(np.sum(feels * weights)),
                max_feels_like_c=float(feels.max()),
                sun_fraction=float(
                    np.sum(
                        np.asarray([c.mean_f_sun for c in costs], dtype=np.float64)
                        * weights
                    )
                ),
            )
        )
    return TimeseriesResponse(route_id=route_id, points=points)


@app.get("/api/departure-curve", response_model=DepartureCurveResponse)
def departure_curve(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float,
    from_iso: datetime, hours: int = Query(default=4, ge=1, le=12),
    walk_speed_ms: float = Query(default=1.35, gt=0.3, le=3.0),
) -> DepartureCurveResponse:
    state = _state()
    with state.runtime_lock.read():
        return _departure_curve_locked(
            origin_lat,
            origin_lon,
            dest_lat,
            dest_lon,
            from_iso,
            hours,
            walk_speed_ms,
            state,
        )


def _departure_curve_locked(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    from_iso: datetime,
    hours: int,
    walk_speed_ms: float,
    state: AppState,
) -> DepartureCurveResponse:
    """Re-route at 15-minute departures across the window. The horizon cache
    makes each search an array-lookup exercise; the searches share nothing —
    which is exactly why they run in parallel here.

    Threads, not processes: the work is numpy over a horizon cache that every
    thread reads and none writes (it is warmed before the sweep starts, below),
    and numpy drops the GIL for the array maths. Processes would have to ship a
    75 MB cache to each worker and would lose more than they gained."""
    graph = state.graph
    origin = graph.nearest_node(origin_lon, origin_lat)
    destination = graph.nearest_node(dest_lon, dest_lat)
    steps = hours * 4  # 15-minute resolution, per the spec
    departures = [from_iso + timedelta(minutes=15 * i) for i in range(steps)]

    def one(depart: datetime) -> DeparturePoint | None:
        try:
            model = _cost_model((origin_lon, origin_lat), depart, walk_speed_ms)
            paths = timedep.solve(graph, origin, destination, depart, model)
        except Exception:
            paths = []
        if not paths:
            return None  # failed departures are dropped, never NaN — bare NaN
            # is invalid JSON and would kill JSON.parse in the browser
        best = min(paths, key=lambda p: p.heat_dm / max(p.duration_s / 60.0, 1e-6))
        return DeparturePoint(
            depart_iso=depart,
            best_mean_feels_like_c=best.mean_feels_like_c,
            best_duration_s=best.duration_s,
        )

    if not state.horizon.warm.all():
        # a cold cache would have the threads racing to write the same entries;
        # do the first departure alone so the corridor is warm, then fan out
        first = one(departures[0]) if departures else None
        rest = departures[1:]
    else:
        first, rest = None, departures

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(rest)))) as pool:
        results = list(pool.map(one, rest)) if rest else []
    if first is not None:
        results.insert(0, first)
    points = [point for point in results if point is not None]

    best_index = (
        min(range(len(points)), key=lambda i: points[i].best_mean_feels_like_c)
        if points
        else 0
    )
    return DepartureCurveResponse(points=points, now_index=0, best_index=best_index)


@app.get("/api/weather", response_model=WeatherSnapshot)
def weather(lat: float, lon: float, at_iso: datetime) -> WeatherSnapshot:
    return _state().weather.at(lat, lon, at_iso)


@app.get("/api/geocode")
def geocode(
    q: str = Query(min_length=2, max_length=120),
) -> dict[str, object]:
    """Search NYC after an explicit submit; never as typeahead."""
    try:
        results = GEOCODER.search(q)
    except GeocoderUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"results": results, "attribution": ATTRIBUTION}


@app.get("/api/amenities")
def amenities(bbox: str) -> list[dict[str, object]]:
    """Pins for the current viewport. Served off the in-memory index rather
    than re-reading the parquet, because the map asks for this on every pan."""
    west, south, east, north = (float(v) for v in bbox.split(","))
    return [
        {"amenity_id": r["amenity_id"], "kind": r["kind"], "name": r["name"],
         "lat": r["lat"], "lon": r["lon"]}
        for r in _state().amenities.records
        if west <= r["lon"] <= east and south <= r["lat"] <= north
    ]


@app.get("/api/buildings")
def buildings(
    bbox: str, max_features: int = Query(default=4000, ge=1, le=20000)
) -> dict[str, object]:
    """Occluder footprints for the viewport, so the client can cast its own
    shadows on the GPU.

    This is the same building set the ray caster uses — the shadows on screen
    and the shade in the routing come from one source, which is the whole
    reason to serve it rather than let the basemap supply its own.

    Tallest first, so a truncated response loses the buildings that matter
    least. Returned as plain dicts, like /api/amenities: it is map furniture,
    not part of the frozen route contract.
    """
    state = _state()
    west, south, east, north = (float(v) for v in bbox.split(","))
    (x0, x1), (y0, y1) = _ll_to_xy_box(west, south, east, north)
    box = shapely.box(x0, y0, x1, y1)
    hits = state.scene.building_tree.query(box)
    if len(hits) == 0:
        return {"buildings": [], "truncated": False}

    heights = (
        state.scene.building_bases_m[hits] + state.scene.building_heights_m[hits]
    )
    order = np.argsort(-heights)[:max_features]
    out = []
    for index in hits[order]:
        geom = state.scene.building_geoms[int(index)]
        ring = getattr(geom, "exterior", None)
        if ring is None:
            continue
        coords = shapely.get_coordinates(ring)
        lon, lat = _to_ll.transform(coords[:, 0], coords[:, 1])
        out.append(
            {
                "building_id": int(index),
                "height_m": float(state.scene.building_heights_m[int(index)]),
                "base_m": float(state.scene.building_bases_m[int(index)]),
                "polygon": [
                    [round(float(a), 6), round(float(b), 6)]
                    for a, b in zip(lon, lat)
                ],
            }
        )
    return {"buildings": out, "truncated": bool(len(hits) > max_features)}


def _ll_to_xy_box(west: float, south: float, east: float, north: float):
    corners = [
        _ll_to_xy(south, west), _ll_to_xy(south, east),
        _ll_to_xy(north, west), _ll_to_xy(north, east),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), max(xs)), (min(ys), max(ys))


@app.post("/api/scene/plant", response_model=PlantResponse)
def plant(req: PlantRequest) -> PlantResponse:
    if not _planting_enabled():
        raise HTTPException(403, "tree planting is disabled on this deployment")
    state = _state()
    with state.runtime_lock.write():
        return _plant_locked(req, state)


def _plant_locked(req: PlantRequest, state: AppState) -> PlantResponse:
    """Plant trees and invalidate exactly what they can shade. The crowns go
    into the live scene (scene_edit.py), so re-routing a corridor reflects the
    new shade immediately — that is the whole point of the feature."""
    from shadeway import occluder, scene_edit

    # Reject coordinates far outside the loaded graph. Besides catching a bad
    # click, this prevents a public caller from growing a global scene full of
    # objects the application can never route past.
    node_lonlat = state.graph.node_lonlat
    lon_lo, lat_lo = np.min(node_lonlat, axis=0) - 0.01
    lon_hi, lat_hi = np.max(node_lonlat, axis=0) + 0.01
    if any(
        not (lon_lo <= point.lon <= lon_hi and lat_lo <= point.lat <= lat_hi)
        for point in req.positions
    ):
        raise HTTPException(422, "plant positions must be inside the loaded city")

    positions = [_ll_to_xy(p.lat, p.lon) for p in req.positions]
    if not positions:
        return PlantResponse(planted=0, invalidated_samples=0,
                             scene_version=state.scene.version)

    geoms = [scene_edit.crown_geometry(req.species, req.dbh_cm)
             for _ in positions]
    radii, bases, tops, taus = (np.array(v) for v in zip(*geoms))
    # invalidate before inserting: warm entries are recomputed lazily against
    # the NEW scene on the next query
    # A crown can alter any horizon ray that reaches it, not only samples under
    # the crown. The ray caster looks 400 m ahead, so the old crown+12 m radius
    # left most affected warm entries permanently stale at low sun angles.
    invalidated = sum(
        state.horizon.invalidate_within(
            x,
            y,
            occluder.RAY_CAP_M + float(radius),
        )
        for (x, y), radius in zip(positions, radii)
    )
    state.scene.plant_crowns(
        xy=np.array(positions),
        crown_radius_m=radii,
        crown_base_m=bases,
        crown_top_m=tops,
        tau=taus,
        species=req.species,
    )
    return PlantResponse(
        planted=len(positions),
        invalidated_samples=invalidated,
        scene_version=state.scene.version,
    )


_to_xy = None


def _ll_to_xy(lat: float, lon: float) -> tuple[float, float]:
    global _to_xy
    if _to_xy is None:
        from pyproj import Transformer

        _to_xy = Transformer.from_crs("EPSG:4326", f"EPSG:{CRS_EPSG}", always_xy=True)
    x, y = _to_xy.transform(lon, lat)
    return float(x), float(y)


# --------------------------------------------------------------- the client
#
# Serving the built SPA from the same process makes the whole thing ONE
# deployable unit: no separate static host, no CORS in production, no second
# URL to keep in sync. In development this directory does not exist and Vite
# serves the client on :5173 instead, proxying /api here — which is why this is
# conditional rather than required.
#
# Mounted last, on purpose. Every /api route above is already registered, and
# Starlette matches routes in order, so the catch-all mount cannot shadow them.
_WEB_DIST = Path(
    os.environ.get("SHADEWAY_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist")
)

if (_WEB_DIST / "index.html").exists():
    from fastapi.staticfiles import StaticFiles

    class CachedStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            # Vite content-hashes every asset filename, so it is safe to cache
            # those forever. index.html must revalidate so a deploy can point at
            # the new hashes immediately.
            if response.status_code == 200 and path.startswith("assets/"):
                response.headers["cache-control"] = "public, max-age=31536000, immutable"
            elif response.status_code == 200:
                response.headers["cache-control"] = "no-cache"
            return response

    app.mount("/", CachedStaticFiles(directory=str(_WEB_DIST), html=True), name="web")
