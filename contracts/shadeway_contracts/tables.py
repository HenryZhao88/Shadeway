"""Frozen on-disk table schemas. Changing these breaks pipeline and server together.

Geometry is stored as WKB in EPSG:32118 (NAD83 / New York Long Island, metres).
Every float column name ends in its unit.
"""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

CRS_EPSG = 32118
SAMPLE_SPACING_M = 10.0
AZIMUTH_BINS = 72
HORIZON_LAYERS = 2  # 0 = opaque (buildings), 1 = canopy (trees)


class EdgeKind(IntEnum):
    SIDEWALK = 0
    CROSSING = 1


class Side(IntEnum):
    NONE = -1  # crossings and any edge with no left/right identity
    LEFT = 0
    RIGHT = 1


class AmenityKind(IntEnum):
    DRINKING_FOUNTAIN = 0
    COOLING_CENTER = 1
    PARK_ENTRANCE = 2


class SchemaError(ValueError):
    """Raised with every mismatch listed, not just the first."""


NODES = pa.schema(
    [
        pa.field("node_id", pa.uint32(), nullable=False),
        pa.field("x_m", pa.float64(), nullable=False),
        pa.field("y_m", pa.float64(), nullable=False),
        pa.field("lon", pa.float64(), nullable=False),
        pa.field("lat", pa.float64(), nullable=False),
        pa.field("is_intersection", pa.bool_(), nullable=False),
        pa.field("borough", pa.string(), nullable=False),
    ]
)

EDGES = pa.schema(
    [
        pa.field("edge_id", pa.uint32(), nullable=False),
        pa.field("u", pa.uint32(), nullable=False),
        pa.field("v", pa.uint32(), nullable=False),
        pa.field("kind", pa.uint8(), nullable=False),  # EdgeKind
        pa.field("side", pa.int8(), nullable=False),  # Side
        pa.field("street_name", pa.string(), nullable=False),
        pa.field("physical_id", pa.int64(), nullable=False),  # CSCL parent segment
        pa.field("bearing_deg", pa.float32(), nullable=False),  # u->v, 0=N, cw
        pa.field("length_m", pa.float32(), nullable=False),
        pa.field("width_m", pa.float32(), nullable=True),  # from planimetric sidewalks
        pa.field("sample_start", pa.uint32(), nullable=False),
        pa.field("sample_count", pa.uint16(), nullable=False),
        pa.field("geom_wkb", pa.binary(), nullable=False),  # LineString, EPSG:32118
    ]
)

SAMPLES = pa.schema(
    [
        pa.field("sample_id", pa.uint32(), nullable=False),  # == row index
        pa.field("edge_id", pa.uint32(), nullable=False),
        pa.field("t", pa.float32(), nullable=False),  # 0..1 along the edge
        pa.field("x_m", pa.float64(), nullable=False),
        pa.field("y_m", pa.float64(), nullable=False),
        pa.field("ground_albedo", pa.float32(), nullable=False),
        pa.field("landcover_class", pa.uint8(), nullable=False),
    ]
)

BUILDINGS = pa.schema(
    [
        pa.field("building_id", pa.uint32(), nullable=False),
        pa.field("height_m", pa.float32(), nullable=False),  # heightroof
        pa.field("base_m", pa.float32(), nullable=False),  # ground elevation offset
        pa.field("geom_wkb", pa.binary(), nullable=False),  # Polygon, EPSG:32118
    ]
)

TREES = pa.schema(
    [
        pa.field("tree_id", pa.uint32(), nullable=False),
        pa.field("x_m", pa.float64(), nullable=False),
        pa.field("y_m", pa.float64(), nullable=False),
        pa.field("species", pa.string(), nullable=False),  # spc_latin, "" if unknown
        pa.field("dbh_cm", pa.float32(), nullable=False),
        pa.field("crown_radius_m", pa.float32(), nullable=False),
        pa.field("crown_base_m", pa.float32(), nullable=False),
        pa.field("crown_top_m", pa.float32(), nullable=False),
        pa.field("tau", pa.float32(), nullable=False),  # direct-beam transmissivity
        pa.field("tau_source", pa.string(), nullable=False),  # citation or "default"
    ]
)

AMENITIES = pa.schema(
    [
        pa.field("amenity_id", pa.uint32(), nullable=False),
        pa.field("kind", pa.uint8(), nullable=False),  # AmenityKind
        pa.field("name", pa.string(), nullable=False),
        pa.field("x_m", pa.float64(), nullable=False),
        pa.field("y_m", pa.float64(), nullable=False),
        pa.field("lon", pa.float64(), nullable=False),
        pa.field("lat", pa.float64(), nullable=False),
    ]
)

ALL_TABLES: dict[str, pa.Schema] = {
    "nodes": NODES,
    "edges": EDGES,
    "samples": SAMPLES,
    "buildings": BUILDINGS,
    "trees": TREES,
    "amenities": AMENITIES,
}


def validate_table(name: str, table: pa.Table) -> None:
    expected = ALL_TABLES[name]
    actual = {f.name: f.type for f in table.schema}
    problems: list[str] = []
    for field in expected:
        if field.name not in actual:
            problems.append(f"missing column {field.name} ({field.type})")
        elif actual[field.name] != field.type:
            problems.append(
                f"column {field.name} has type {actual[field.name]}, expected {field.type}"
            )
        elif not field.nullable and table.column(field.name).null_count:
            problems.append(f"column {field.name} contains null values but is required")
    for extra in set(actual) - {f.name for f in expected}:
        problems.append(f"unexpected column {extra}")
    if problems:
        raise SchemaError(f"table {name!r} does not conform:\n  " + "\n  ".join(problems))


def read_table(path: Path) -> pa.Table:
    table = pq.read_table(path)
    validate_table(Path(path).stem, table)
    return table
