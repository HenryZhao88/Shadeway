"""Fixture-backed stand-in for the real API. Same URLs, same shapes, fake numbers.

Track C builds the entire client against this. Plan 02 Task 11 replaces it with
`shadeway.api`, which must serve byte-compatible shapes at the same paths.
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from shadeway_contracts.api import (
    DepartureCurveResponse,
    DeparturePoint,
    PlantRequest,
    PlantResponse,
    RouteRequest,
    RouteResponse,
    TimeseriesPoint,
    TimeseriesResponse,
    WeatherSnapshot,
)
from shadeway_contracts.fixtures import example_route_response

app = FastAPI(title="shadeway (stub)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STUB_DELAY_MS = float(os.environ.get("SHADEWAY_STUB_DELAY_MS", "120"))


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "scene": "stub",
        "cache_warm": True,
        "planting_enabled": True,
    }


@app.post("/api/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    time.sleep(STUB_DELAY_MS / 1000.0)
    base = example_route_response()
    # shift the canned response onto the requested departure time so the client's
    # scrubber has something that moves
    shift = req.depart_iso - base.routes["fastest"].depart_iso
    return base.model_copy(
        update={
            "computed_at": req.depart_iso,
            "routes": {
                rid: r.model_copy(
                    update={
                        "depart_iso": r.depart_iso + shift,
                        "arrive_iso": r.arrive_iso + shift,
                        "legs": [
                            leg.model_copy(
                                update={
                                    "enter_iso": leg.enter_iso + shift,
                                    "exit_iso": leg.exit_iso + shift,
                                }
                            )
                            for leg in r.legs
                        ],
                    }
                )
                for rid, r in base.routes.items()
            },
        }
    )


@app.get("/api/route/{route_id}/timeseries", response_model=TimeseriesResponse)
def timeseries(
    route_id: str,
    depart_iso: datetime,
    step_minutes: int = Query(default=5, ge=1, le=60),
) -> TimeseriesResponse:
    base = example_route_response().routes.get(route_id)
    duration_min = (base.duration_s / 60.0) if base else 20.0
    mean_c = base.feels_like_c.mean_c if base else 35.0
    steps = max(4, int(duration_min // step_minutes) + 1)
    points = [
        TimeseriesPoint(
            at_iso=depart_iso + timedelta(minutes=i * step_minutes),
            mean_feels_like_c=mean_c + 2.0 * math.sin(i / 2.0),
            max_feels_like_c=mean_c + 5.0 + 2.0 * math.sin(i / 2.0),
            sun_fraction=0.5 + 0.3 * math.sin(i / 3.0),
        )
        for i in range(steps)
    ]
    return TimeseriesResponse(route_id=route_id, points=points)


@app.get("/api/departure-curve", response_model=DepartureCurveResponse)
def departure_curve(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float,
    from_iso: datetime, hours: int = Query(default=4, ge=1, le=12),
) -> DepartureCurveResponse:
    steps = hours * 4  # 15-minute resolution, per the spec
    points = [
        DeparturePoint(
            depart_iso=from_iso + timedelta(minutes=15 * i),
            # a plausible bowl: cools through the afternoon, bottoms near the end
            best_mean_feels_like_c=41.0 - 8.0 * (i / max(1, steps - 1)) ** 0.8,
            best_duration_s=1380.0,
        )
        for i in range(steps)
    ]
    best = min(range(steps), key=lambda i: points[i].best_mean_feels_like_c)
    return DepartureCurveResponse(points=points, now_index=0, best_index=best)


@app.get("/api/weather", response_model=WeatherSnapshot)
def weather(lat: float, lon: float, at_iso: datetime) -> WeatherSnapshot:
    return example_route_response().weather.model_copy(update={"observed_iso": at_iso})


@app.get("/api/amenities")
def amenities(bbox: str) -> list[dict[str, object]]:
    from shadeway_contracts.fixtures import build_fixture_city

    table = build_fixture_city()["amenities"].to_pylist()
    return [
        {"amenity_id": r["amenity_id"], "kind": r["kind"], "name": r["name"],
         "lat": r["lat"], "lon": r["lon"]}
        for r in table
    ]


@app.get("/api/buildings")
def buildings(
    bbox: str, max_features: int = Query(default=4000, ge=1, le=20000)
) -> dict[str, object]:
    """The fixture city's prisms, in lon/lat, so the client draws real shadows
    against the stub too. Without this the documented no-download path
    (`make stub` + `make dev`) would open on a city with no shade in it, which
    is the one thing the first five seconds of the demo is about."""
    import shapely
    from pyproj import Transformer

    from shadeway_contracts.fixtures import build_fixture_city
    from shadeway_contracts.tables import CRS_EPSG

    to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)
    west, south, east, north = (float(v) for v in bbox.split(","))
    table = build_fixture_city()["buildings"].to_pylist()

    out: list[dict[str, object]] = []
    for row in table:
        geom = shapely.from_wkb(row["geom_wkb"])
        ring = getattr(geom, "exterior", None)
        if ring is None:
            continue
        coords = shapely.get_coordinates(ring)
        lon, lat = to_ll.transform(coords[:, 0], coords[:, 1])
        polygon = [[float(a), float(b)] for a, b in zip(lon, lat)]
        if not any(
            west <= x <= east and south <= y <= north for x, y in polygon
        ):
            continue
        out.append(
            {
                "building_id": int(row["building_id"]),
                "height_m": float(row["height_m"]),
                "base_m": float(row["base_m"]),
                "polygon": polygon,
            }
        )
    return {"buildings": out[:max_features], "truncated": len(out) > max_features}


@app.post("/api/scene/plant", response_model=PlantResponse)
def plant(req: PlantRequest) -> PlantResponse:
    return PlantResponse(
        planted=len(req.positions),
        invalidated_samples=len(req.positions) * 24,
        scene_version=2,
    )
