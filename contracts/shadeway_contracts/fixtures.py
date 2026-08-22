"""A deterministic synthetic Manhattan-ish grid, conforming to every frozen schema.

Track B develops the engine against this before any real data exists.
Track C's stub server serves the route response built from it.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from shapely.geometry import LineString, Polygon

from shadeway_contracts import api
from shadeway_contracts.tables import (
    ALL_TABLES,
    AMENITIES,
    BUILDINGS,
    CRS_EPSG,
    EDGES,
    NODES,
    SAMPLES,
    TREES,
    AmenityKind,
    EdgeKind,
    SAMPLE_SPACING_M,
    Side,
)

# Anchored on Bryant Park so the fixture lands on the real basemap during dev.
ORIGIN_LON, ORIGIN_LAT = -73.9840, 40.7536
BLOCK_M = 80.0
GRID = 6
SIDEWALK_OFFSET_M = 8.0
EDT = timezone(timedelta(hours=-4))

_to_m = Transformer.from_crs("EPSG:4326", f"EPSG:{CRS_EPSG}", always_xy=True)
_to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)

FIXTURE_ORIGIN = api.LatLon(lat=ORIGIN_LAT, lon=ORIGIN_LON)


def _grid_nodes() -> tuple[np.ndarray, np.ndarray]:
    x0, y0 = _to_m.transform(ORIGIN_LON, ORIGIN_LAT)
    ix, iy = np.meshgrid(np.arange(GRID), np.arange(GRID), indexing="ij")
    return x0 + ix.ravel() * BLOCK_M, y0 + iy.ravel() * BLOCK_M


def _offset(line: LineString, side: Side) -> LineString:
    # positive offset is left of travel in shapely
    distance = SIDEWALK_OFFSET_M if side == Side.LEFT else -SIDEWALK_OFFSET_M
    return LineString(line.parallel_offset(distance, "left" if distance > 0 else "right").coords)


def _sample_line(line: LineString) -> np.ndarray:
    n = max(2, int(np.ceil(line.length / SAMPLE_SPACING_M)) + 1)
    ts = np.linspace(0.0, 1.0, n)
    pts = np.array([line.interpolate(t, normalized=True).coords[0] for t in ts])
    return np.column_stack([ts, pts])


def build_fixture_city(seed: int = 7) -> dict[str, pa.Table]:
    rng = np.random.default_rng(seed)
    xs, ys = _grid_nodes()

    def nid(i: int, j: int) -> int:
        return i * GRID + j

    nodes_lon, nodes_lat = _to_ll.transform(xs, ys)
    nodes = pa.table(
        {
            "node_id": pa.array(np.arange(len(xs)), type=pa.uint32()),
            "x_m": pa.array(xs, type=pa.float64()),
            "y_m": pa.array(ys, type=pa.float64()),
            "lon": pa.array(nodes_lon, type=pa.float64()),
            "lat": pa.array(nodes_lat, type=pa.float64()),
            "is_intersection": pa.array(np.ones(len(xs), bool), type=pa.bool_()),
            "borough": pa.array(["1"] * len(xs), type=pa.string()),
        },
        schema=NODES,
    )

    edge_rows: list[dict] = []
    sample_rows: list[dict] = []
    physical_id = 0

    def add_edge(u: int, v: int, line: LineString, kind: EdgeKind, side: Side,
                 name: str, parent: int) -> None:
        s = _sample_line(line)
        start = len(sample_rows)
        for t, x, y in s:
            # class 1 = asphalt roadway, 2 = concrete sidewalk (fixture convention)
            cls = 1 if kind == EdgeKind.CROSSING else 2
            sample_rows.append(
                {
                    "sample_id": len(sample_rows),
                    "edge_id": len(edge_rows),
                    "t": float(t),
                    "x_m": float(x),
                    "y_m": float(y),
                    "ground_albedo": 0.12 if cls == 1 else 0.25,
                    "landcover_class": cls,
                }
            )
        (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
        bearing = (np.degrees(np.arctan2(bx - ax, by - ay)) + 360.0) % 360.0
        edge_rows.append(
            {
                "edge_id": len(edge_rows),
                "u": u,
                "v": v,
                "kind": int(kind),
                "side": int(side),
                "street_name": name,
                "physical_id": parent,
                "bearing_deg": float(bearing),
                "length_m": float(line.length),
                "width_m": 4.0 if kind == EdgeKind.SIDEWALK else None,
                "sample_start": start,
                "sample_count": len(sample_rows) - start,
                "geom_wkb": line.wkb,
            }
        )

    for i in range(GRID):
        for j in range(GRID):
            for di, dj, name in ((1, 0, f"{j}th Ave"), (0, 1, f"{40 + i}th St")):
                ni, nj = i + di, j + dj
                if ni >= GRID or nj >= GRID:
                    continue
                centre = LineString(
                    [(xs[nid(i, j)], ys[nid(i, j)]), (xs[nid(ni, nj)], ys[nid(ni, nj)])]
                )
                physical_id += 1
                for side in (Side.LEFT, Side.RIGHT):
                    add_edge(
                        nid(i, j), nid(ni, nj), _offset(centre, side),
                        EdgeKind.SIDEWALK, side, name, physical_id,
                    )

    # crossings: at each intersection, connect the two sidewalk sides across the node
    for i in range(GRID):
        for j in range(GRID):
            n = nid(i, j)
            x, y = xs[n], ys[n]
            physical_id += 1
            add_edge(
                n, n,
                LineString([(x - SIDEWALK_OFFSET_M, y), (x + SIDEWALK_OFFSET_M, y)]),
                EdgeKind.CROSSING, Side.NONE, "crossing", physical_id,
            )

    edges = pa.Table.from_pylist(edge_rows, schema=EDGES)
    samples = pa.Table.from_pylist(sample_rows, schema=SAMPLES)

    # one tall building per block interior, plus a very tall one for a hard shadow
    bx, by, bh, bid = [], [], [], []
    polys = []
    for i in range(GRID - 1):
        for j in range(GRID - 1):
            cx = xs[nid(i, j)] + BLOCK_M / 2
            cy = ys[nid(i, j)] + BLOCK_M / 2
            half = BLOCK_M / 2 - SIDEWALK_OFFSET_M - 2.0
            polys.append(
                Polygon(
                    [
                        (cx - half, cy - half),
                        (cx + half, cy - half),
                        (cx + half, cy + half),
                        (cx - half, cy + half),
                    ]
                )
            )
            bh.append(float(rng.uniform(12.0, 55.0)))
            bid.append(len(bid))
    bh[len(bh) // 2] = 180.0  # the guaranteed hard occluder
    buildings = pa.table(
        {
            "building_id": pa.array(bid, type=pa.uint32()),
            "height_m": pa.array(bh, type=pa.float32()),
            "base_m": pa.array(np.zeros(len(bid)), type=pa.float32()),
            "geom_wkb": pa.array([p.wkb for p in polys], type=pa.binary()),
        },
        schema=BUILDINGS,
    )

    # street trees every 20 m along every sidewalk edge, alternating two species
    # tau values here are FIXTURE PLACEHOLDERS; the real values arrive in Plan 01 Task 6.
    tx, ty, tsp, tdbh, trad, tbase, ttop, ttau, tsrc = ([] for _ in range(9))
    for row in edge_rows:
        if row["kind"] != EdgeKind.SIDEWALK:
            continue
        sl = slice(row["sample_start"], row["sample_start"] + row["sample_count"])
        for k, s in enumerate(sample_rows[sl]):
            if k % 2:
                continue
            airy = (len(tx) % 2) == 0
            tx.append(s["x_m"] + rng.uniform(-1, 1))
            ty.append(s["y_m"] + rng.uniform(-1, 1))
            tsp.append("Gleditsia triacanthos" if airy else "Platanus x acerifolia")
            tdbh.append(float(rng.uniform(15, 45)))
            trad.append(float(rng.uniform(3.0, 6.0)))
            tbase.append(2.5)
            ttop.append(float(rng.uniform(8.0, 14.0)))
            ttau.append(0.35 if airy else 0.15)
            tsrc.append("fixture placeholder — see plan 01 task 6")
    trees = pa.table(
        {
            "tree_id": pa.array(np.arange(len(tx)), type=pa.uint32()),
            "x_m": pa.array(tx, type=pa.float64()),
            "y_m": pa.array(ty, type=pa.float64()),
            "species": pa.array(tsp, type=pa.string()),
            "dbh_cm": pa.array(tdbh, type=pa.float32()),
            "crown_radius_m": pa.array(trad, type=pa.float32()),
            "crown_base_m": pa.array(tbase, type=pa.float32()),
            "crown_top_m": pa.array(ttop, type=pa.float32()),
            "tau": pa.array(ttau, type=pa.float32()),
            "tau_source": pa.array(tsrc, type=pa.string()),
        },
        schema=TREES,
    )

    amen_idx = [nid(1, 1), nid(3, 2), nid(4, 4)]
    kinds = [AmenityKind.DRINKING_FOUNTAIN, AmenityKind.COOLING_CENTER,
             AmenityKind.PARK_ENTRANCE]
    alon, alat = _to_ll.transform(xs[amen_idx], ys[amen_idx])
    amenities = pa.table(
        {
            "amenity_id": pa.array(np.arange(len(amen_idx)), type=pa.uint32()),
            "kind": pa.array([int(k) for k in kinds], type=pa.uint8()),
            "name": pa.array(["Fixture Fountain", "Fixture Cooling Center",
                              "Fixture Park Entrance"], type=pa.string()),
            "x_m": pa.array(xs[amen_idx], type=pa.float64()),
            "y_m": pa.array(ys[amen_idx], type=pa.float64()),
            "lon": pa.array(alon, type=pa.float64()),
            "lat": pa.array(alat, type=pa.float64()),
        },
        schema=AMENITIES,
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "samples": samples,
        "buildings": buildings,
        "trees": trees,
        "amenities": amenities,
    }


FIXTURE_DEST = api.LatLon(lat=ORIGIN_LAT + 0.0035, lon=ORIGIN_LON + 0.0040)


def write_fixture_city(out_dir: Path, seed: int = 7) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in build_fixture_city(seed).items():
        pq.write_table(table, out_dir / f"{name}.parquet")


def _leg(edge_id: int, name: str, side: int, coords, enter, secs, feels, f_sun, svf):
    return api.LegStep(
        edge_id=edge_id, street_name=name, side=side, kind=int(EdgeKind.SIDEWALK),
        geometry=coords, length_m=secs * 1.35,
        enter_iso=enter, exit_iso=enter + timedelta(seconds=secs),
        feels_like_c=feels, tmrt_c=feels + 8.0, f_sun=f_sun, svf=svf,
    )


def example_route_response() -> api.RouteResponse:
    """A hand-built, fully-populated response. The stub server serves this and the
    web client's tests assert against it."""
    depart = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)
    weather = api.WeatherSnapshot(
        observed_iso=depart, air_temp_c=30.6, relative_humidity_pct=48.0,
        wind_speed_10m_ms=3.4, cloud_cover_pct=6.0, direct_normal_wm2=799.0,
        diffuse_wm2=148.0, global_horizontal_wm2=712.0, uv_index=8.0,
    )
    o, d = FIXTURE_ORIGIN, FIXTURE_DEST
    mid = (o.lon + 0.002, o.lat + 0.001)

    fastest = api.Route(
        route_id="fastest", label="fastest", depart_iso=depart,
        arrive_iso=depart + timedelta(minutes=18), duration_s=1080.0, distance_m=1458.0,
        feels_like_c=api.FeelsLike(mean_c=41.0, max_c=45.2, p90_c=44.1),
        exposure=api.Exposure(sun_fraction=0.78, mean_svf=0.61, canopy_fraction=0.08),
        legs=[
            _leg(101, "5th Ave", int(Side.LEFT), [(o.lon, o.lat), mid], depart, 540,
                 42.4, 0.9, 0.66),
            _leg(140, "42nd St", int(Side.LEFT), [mid, (d.lon, d.lat)],
                 depart + timedelta(seconds=540), 540, 39.6, 0.66, 0.56),
        ],
        instructions=[
            api.Instruction(type="start", at=o, text="Head north on the west side of 5th Ave"),
            api.Instruction(type="turn", at=api.LatLon(lat=mid[1], lon=mid[0]),
                            text="Turn right onto 42nd St"),
            api.Instruction(type="arrive", at=d, text="Arrive"),
        ],
    )
    shadeway = api.Route(
        route_id="shadeway", label="shadeway", depart_iso=depart,
        arrive_iso=depart + timedelta(minutes=23), duration_s=1380.0, distance_m=1863.0,
        feels_like_c=api.FeelsLike(mean_c=33.0, max_c=38.4, p90_c=36.9),
        exposure=api.Exposure(sun_fraction=0.24, mean_svf=0.38, canopy_fraction=0.31),
        legs=[
            _leg(102, "5th Ave", int(Side.RIGHT), [(o.lon, o.lat), mid], depart, 700,
                 32.1, 0.05, 0.34),
            _leg(141, "42nd St", int(Side.RIGHT), [mid, (d.lon, d.lat)],
                 depart + timedelta(seconds=700), 680, 33.9, 0.42, 0.42),
        ],
        instructions=[
            api.Instruction(
                type="cross", at=o,
                text="Cross to the east side of 5th Ave at 42nd",
                why=api.InstructionWhy(
                    sunlit_until_iso=datetime(2025, 7, 22, 18, 40, tzinfo=EDT),
                    shaded_by="500 Fifth Avenue", delta_c=5.0, dappled=False,
                ),
            ),
            api.Instruction(
                type="continue", at=api.LatLon(lat=mid[1], lon=mid[0]),
                text="Continue on the north side of 42nd St",
                why=api.InstructionWhy(shaded_by="honey locust canopy", dappled=True),
            ),
            api.Instruction(type="arrive", at=d, text="Arrive"),
        ],
    )
    return api.RouteResponse(
        request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "shadeway-fixture")),
        computed_at=depart, weather=weather,
        frontier=[
            api.FrontierPoint(route_id="fastest", duration_s=1080.0,
                              mean_feels_like_c=41.0),
            api.FrontierPoint(route_id="shadeway", duration_s=1380.0,
                              mean_feels_like_c=33.0),
        ],
        routes={"fastest": fastest, "shadeway": shadeway},
        chosen_route_id="shadeway",
        cache_warm=True, compute_ms=42.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="write the shadeway fixture city")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    write_fixture_city(args.out, args.seed)
    total = sum(t.num_rows for t in build_fixture_city(args.seed).values())
    print(f"wrote {len(ALL_TABLES)} tables ({total} rows) to {args.out}")


if __name__ == "__main__":
    main()
