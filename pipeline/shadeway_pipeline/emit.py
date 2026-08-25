"""Run the whole pipeline and write the six parquet files.

    python -m shadeway_pipeline.emit --out data/nyc --scope manhattan
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer

from shadeway_contracts.tables import (
    ALL_TABLES,
    AMENITIES,
    BUILDINGS,
    CRS_EPSG,
    EDGES,
    NODES,
    SAMPLES,
    TREES,
)
from shadeway_pipeline.config import DEFAULT_SCOPE, OUT_DIR, SCOPES, Scope
from shadeway_pipeline.graph import build as graph_build
from shadeway_pipeline.graph import crossings, sample
from shadeway_pipeline.scene import buildings as scene_buildings
from shadeway_pipeline.scene import trees as scene_trees
from shadeway_pipeline.sources import amenities as amenities_src
from shadeway_pipeline.sources import buildings as buildings_src
from shadeway_pipeline.sources import cscl
from shadeway_pipeline.sources import trees as trees_src

_to_ll = Transformer.from_crs(f"EPSG:{CRS_EPSG}", "EPSG:4326", always_xy=True)


def _lonlat(x, y) -> tuple[np.ndarray, np.ndarray]:
    """Vector transform, including pyproj's one-point compatibility edge."""
    x_values = np.asarray(x, dtype=np.float64)
    y_values = np.asarray(y, dtype=np.float64)
    if len(x_values) == 1:
        # Older pyproj mistakes a one-element ndarray for a scalar point and
        # asks NumPy to coerce the whole array, which NumPy is removing.
        lon, lat = _to_ll.transform(float(x_values[0]), float(y_values[0]))
        return np.asarray([lon]), np.asarray([lat])
    lon, lat = _to_ll.transform(x_values, y_values)
    return np.asarray(lon), np.asarray(lat)


def _stage(label: str, start: float) -> float:
    now = time.time()
    print(f"  {label:<28} {now - start:6.1f}s")
    return now


def build_tables(scope: Scope) -> dict[str, pa.Table]:
    print(f"\nbuilding scope {scope.name} (boroughs {scope.boroughs})")
    clock = time.time()

    streets = cscl.load(scope)
    clock = _stage(f"streets ({len(streets)})", clock)

    nodes_df, edges_df = graph_build.build_sidewalk_edges(streets, None)
    clock = _stage(f"sidewalk edges ({len(edges_df)})", clock)

    nodes_df, edges_df = crossings.add_crossings(nodes_df, edges_df)
    clock = _stage(f"crossings ({len(edges_df)} total)", clock)

    edges_df, samples_df = sample.add_samples(edges_df)
    clock = _stage(f"samples ({len(samples_df)})", clock)

    footprints = buildings_src.load(scope)
    prisms = scene_buildings.build_prisms(footprints)
    clock = _stage(f"building prisms ({len(prisms)})", clock)

    crowns = scene_trees.build_crowns(trees_src.load(scope))
    clock = _stage(f"tree crowns ({len(crowns)})", clock)

    # park entrances are derived against the pedestrian network, so the graph
    # has to exist before amenities are built — see sources/parks.py
    amen = amenities_src.load(scope, sidewalk_geoms=list(edges_df["geometry"]))
    clock = _stage(f"amenities ({len(amen)})", clock)

    lon, lat = _lonlat(
        nodes_df["x_m"].to_numpy(), nodes_df["y_m"].to_numpy()
    )
    nodes = pa.table(
        {
            "node_id": pa.array(nodes_df["node_id"].to_numpy(), type=pa.uint32()),
            "x_m": pa.array(nodes_df["x_m"].to_numpy(), type=pa.float64()),
            "y_m": pa.array(nodes_df["y_m"].to_numpy(), type=pa.float64()),
            "lon": pa.array(lon, type=pa.float64()),
            "lat": pa.array(lat, type=pa.float64()),
            "is_intersection": pa.array(
                np.ones(len(nodes_df), dtype=bool), type=pa.bool_()
            ),
            # per node, from the street that created it — not scope.boroughs[0],
            # which labelled all of Brooklyn as Manhattan
            "borough": pa.array(
                [str(b) for b in nodes_df["borough"]], type=pa.string()
            ),
        },
        schema=NODES,
    )

    edges = pa.table(
        {
            "edge_id": pa.array(edges_df["edge_id"].to_numpy(), type=pa.uint32()),
            "u": pa.array(edges_df["u"].to_numpy(), type=pa.uint32()),
            "v": pa.array(edges_df["v"].to_numpy(), type=pa.uint32()),
            "kind": pa.array(edges_df["kind"].to_numpy(), type=pa.uint8()),
            "side": pa.array(edges_df["side"].to_numpy(), type=pa.int8()),
            "street_name": pa.array(edges_df["street_name"], type=pa.string()),
            "physical_id": pa.array(edges_df["physical_id"], type=pa.int64()),
            "bearing_deg": pa.array(edges_df["bearing_deg"], type=pa.float32()),
            "length_m": pa.array(edges_df["length_m"], type=pa.float32()),
            "width_m": pa.array(edges_df["width_m"].astype("float32"), type=pa.float32()),
            "sample_start": pa.array(edges_df["sample_start"], type=pa.uint32()),
            "sample_count": pa.array(edges_df["sample_count"], type=pa.uint16()),
            "geom_wkb": pa.array(
                [g.wkb for g in edges_df["geometry"]], type=pa.binary()
            ),
        },
        schema=EDGES,
    )

    samples = pa.Table.from_pandas(samples_df, schema=SAMPLES, preserve_index=False)
    buildings_tbl = pa.Table.from_pandas(prisms, schema=BUILDINGS, preserve_index=False)
    trees_tbl = pa.Table.from_pandas(crowns, schema=TREES, preserve_index=False)

    amenities_tbl = _amenities_table(amen)

    return {
        "nodes": nodes,
        "edges": edges,
        "samples": samples,
        "buildings": buildings_tbl,
        "trees": trees_tbl,
        "amenities": amenities_tbl,
    }


def _amenities_table(amen) -> pa.Table:
    """The amenities frame as its parquet table. Shared by the full build and
    the amenities-only rebuild, so the two can never drift."""
    if not len(amen):
        return AMENITIES.empty_table()
    ax = np.array([g.x for g in amen.geometry])
    ay = np.array([g.y for g in amen.geometry])
    alon, alat = _lonlat(ax, ay)
    return pa.table(
        {
            "amenity_id": pa.array(np.arange(len(amen)), type=pa.uint32()),
            "kind": pa.array(amen["kind"].to_numpy(), type=pa.uint8()),
            "name": pa.array(list(amen["name"]), type=pa.string()),
            "x_m": pa.array(ax, type=pa.float64()),
            "y_m": pa.array(ay, type=pa.float64()),
            "lon": pa.array(alon, type=pa.float64()),
            "lat": pa.array(alat, type=pa.float64()),
        },
        schema=AMENITIES,
    )


def build_amenities_only(scope: Scope, out_dir: Path) -> dict[str, pa.Table]:
    """Rebuild just the amenities table, against an already-built graph.

    Worth its own path because amenities are the one table nothing else is
    keyed to: horizon.npz is indexed by sample id, so a full `make data` throws
    away a warm cache that took minutes to build. This does not touch it.
    """
    import shapely

    edges = pq.read_table(Path(out_dir) / "edges.parquet")
    geoms = list(shapely.from_wkb(edges.column("geom_wkb").to_pylist()))
    amen = amenities_src.load(scope, sidewalk_geoms=geoms)
    print(f"  amenities ({len(amen)}) against {len(geoms)} existing edges")
    return {"amenities": _amenities_table(amen)}


def write(tables: dict[str, pa.Table], out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ALL_TABLES:
        if name not in tables:
            continue
        path = out_dir / f"{name}.parquet"
        pq.write_table(tables[name], path, compression="zstd")
        print(f"  wrote {path}  ({tables[name].num_rows} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="build shadeway graph + scene")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--scope", choices=sorted(SCOPES), default=DEFAULT_SCOPE)
    parser.add_argument(
        "--only",
        choices=["amenities"],
        help="rebuild one table against the existing build. Use it for "
             "amenities: a full rebuild renumbers sample ids and would "
             "invalidate a warm horizon.npz that took minutes to make.",
    )
    args = parser.parse_args()
    scope = SCOPES[args.scope]
    if args.only == "amenities":
        write(build_amenities_only(scope, args.out), args.out)
        return
    write(build_tables(scope), args.out)
    print(f"\nnow run:  python -m shadeway_pipeline.validate --data {args.out}")


if __name__ == "__main__":
    main()
