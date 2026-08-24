"""The real API. Serves the same paths and shapes as stub_api, backed by physics."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import shapely
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pyproj import Transformer

from shadeway import instructions as instr
from shadeway.cost import EdgeCostModel
from shadeway.horizon import HorizonCache
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
from shadeway_contracts.tables import CRS_EPSG, read_table

_to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)


@dataclass
class AppState:
    graph: Graph
    scene: Scene
    horizon: HorizonCache
    weather: WeatherClient
    data_dir: Path

    @classmethod
    def build(cls) -> "AppState":
        data_dir = Path(os.environ.get("SHADEWAY_DATA", "data/nyc"))
        if not (data_dir / "edges.parquet").exists():
            data_dir = Path("data/fixtures")
        graph = Graph.load(data_dir)
        scene = Scene.load(data_dir)
        horizon = HorizonCache(scene, graph.sample_xy)
        precomputed = data_dir / "horizon.npz"
        if precomputed.exists():
            if horizon.load_precomputed(precomputed):
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
        )


STATE: AppState | None = None


def _state() -> AppState:
    global STATE
    if STATE is None:
        STATE = AppState.build()
    return STATE


app = FastAPI(title="shadeway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ROUTE_CACHE: dict[str, tuple[Route, list[int]]] = {}


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
    }


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
    coords = shapely.get_coordinates(graph.geoms[edge_id])
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


def _to_route(path, route_id: str, label: str, depart: datetime, model) -> Route:
    legs: list[LegStep] = []
    clock = depart
    for edge_id in path.edges:
        cost = model.traverse(edge_id, clock)
        legs.append(_leg(edge_id, clock, cost))
        clock += timedelta(seconds=cost.duration_s)

    feels = np.array([leg.feels_like_c for leg in legs], dtype=np.float64)
    weights = np.array([leg.length_m for leg in legs], dtype=np.float64)
    weights = weights / max(weights.sum(), 1e-9)
    f_sun_arr = np.array([leg.f_sun for leg in legs], dtype=np.float64)
    svf_arr = np.array([leg.svf for leg in legs], dtype=np.float64)
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
            canopy_fraction=float(
                np.mean([(0.0 < f < 0.9) for f in f_sun_arr]) if legs else 0.0
            ),
        ),
        legs=legs,
        instructions=instr.build(_state().graph, path, legs),
    )


@app.post("/api/route", response_model=RouteResponse)
def route(request: RouteRequest) -> RouteResponse:
    started = time.perf_counter()
    state = _state()
    graph = state.graph
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
    routes: dict[str, Route] = {}
    frontier: list[FrontierPoint] = []
    for index, path in enumerate(paths):
        route_id = "fastest" if index == 0 else (
            "shadeway" if index == len(paths) - 1 else f"alt{index}"
        )
        built = _to_route(path, route_id, route_id, request.depart_iso, model)
        routes[route_id] = built
        _ROUTE_CACHE[route_id] = (built, path.edges)
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
        request_id=str(uuid.uuid4()),
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
) -> TimeseriesResponse:
    """The heat-vs-time curve. One call returns the whole series, because it is
    the same sample points evaluated at N different times and the horizon cache
    makes that almost free."""
    cached = _ROUTE_CACHE.get(route_id)
    if cached is None:
        raise HTTPException(404, "unknown route id — request /api/route first")
    built, edges = cached
    lon, lat = built.legs[0].geometry[0]
    model = _cost_model((lon, lat), depart_iso, 1.35)

    steps = max(2, int(built.duration_s / 60.0 / step_minutes) + 1)
    points: list[TimeseriesPoint] = []
    for i in range(steps):
        at = depart_iso + timedelta(minutes=i * step_minutes)
        costs = [model.traverse(e, at) for e in edges]
        feels = np.array([c.mean_feels_like_c for c in costs])
        points.append(
            TimeseriesPoint(
                at_iso=at,
                mean_feels_like_c=float(feels.mean()),
                max_feels_like_c=float(feels.max()),
                sun_fraction=float(np.mean([c.mean_f_sun for c in costs])),
            )
        )
    return TimeseriesResponse(route_id=route_id, points=points)


@app.get("/api/departure-curve", response_model=DepartureCurveResponse)
def departure_curve(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float,
    from_iso: datetime, hours: int = Query(default=4, ge=1, le=12),
) -> DepartureCurveResponse:
    """Re-route at 15-minute departures across the window. The horizon cache
    makes each search an array-lookup exercise; the searches share nothing."""
    state = _state()
    graph = state.graph
    origin = graph.nearest_node(origin_lon, origin_lat)
    destination = graph.nearest_node(dest_lon, dest_lat)
    steps = hours * 4  # 15-minute resolution, per the spec
    points: list[DeparturePoint] = []
    for i in range(steps):
        depart = from_iso + timedelta(minutes=15 * i)
        try:
            model = _cost_model((origin_lon, origin_lat), depart, 1.35)
            paths = timedep.solve(graph, origin, destination, depart, model)
        except Exception:
            paths = []
        if not paths:
            continue  # failed departures are dropped, never NaN — bare NaN is
            # invalid JSON and would kill JSON.parse in the browser
        best = min(paths, key=lambda p: p.heat_dm / max(p.duration_s / 60.0, 1e-6))
        points.append(
            DeparturePoint(
                depart_iso=depart,
                best_mean_feels_like_c=best.mean_feels_like_c,
                best_duration_s=best.duration_s,
            )
        )
    best_index = (
        min(range(len(points)), key=lambda i: points[i].best_mean_feels_like_c)
        if points
        else 0
    )
    return DepartureCurveResponse(points=points, now_index=0, best_index=best_index)


@app.get("/api/weather", response_model=WeatherSnapshot)
def weather(lat: float, lon: float, at_iso: datetime) -> WeatherSnapshot:
    return _state().weather.at(lat, lon, at_iso)


@app.get("/api/amenities")
def amenities(bbox: str) -> list[dict[str, object]]:
    west, south, east, north = (float(v) for v in bbox.split(","))
    table = read_table(_state().data_dir / "amenities.parquet").to_pylist()
    return [
        {"amenity_id": r["amenity_id"], "kind": r["kind"], "name": r["name"],
         "lat": r["lat"], "lon": r["lon"]}
        for r in table
        if west <= r["lon"] <= east and south <= r["lat"] <= north
    ]


@app.post("/api/scene/plant", response_model=PlantResponse)
def plant(req: PlantRequest) -> PlantResponse:
    """Plant trees and invalidate exactly what they can shade. The crowns go
    into the live scene (scene_edit.py), so re-routing a corridor reflects the
    new shade immediately — that is the whole point of the feature."""
    from shadeway import scene_edit

    state = _state()
    positions = [_ll_to_xy(p.lat, p.lon) for p in req.positions]
    if not positions:
        return PlantResponse(planted=0, invalidated_samples=0,
                             scene_version=state.scene.version)

    geoms = [scene_edit.crown_geometry(req.species, req.dbh_cm)
             for _ in positions]
    radii, bases, tops, taus = (np.array(v) for v in zip(*geoms))
    # invalidate before inserting: warm entries are recomputed lazily against
    # the NEW scene on the next query
    reach = float(radii.max()) + 12.0  # crown reach + sample-spacing margin
    invalidated = sum(
        state.horizon.invalidate_within(x, y, reach) for x, y in positions
    )
    state.scene.plant_crowns(
        xy=np.array(positions),
        crown_radius_m=radii,
        crown_base_m=bases,
        crown_top_m=tops,
        tau=taus,
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
