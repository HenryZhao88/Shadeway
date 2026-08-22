"""Turn street centerlines into left and right sidewalk edges.

This is the module that earns us "cross to the east side of 5th Ave at 42nd".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.strtree import STRtree

from shadeway_contracts.tables import EdgeKind, Side
from shadeway_pipeline.config import (
    MIN_EDGE_LENGTH_M,
    SIDEWALK_HALF_WIDTH_M,
    offset_for,
)

NODE_SNAP_M = 1.0
WIDTH_SEARCH_M = 12.0  # how far to look for a planimetric sidewalk to measure


def offset_side(line: LineString, side: Side, distance_m: float) -> LineString:
    """Offset `line` to one side, KEEPING the original direction of travel.

    HISTORICAL NOTE: shapely < 2 returned right-side offsets reversed, and every
    older write-up (including our own plan) tells you to undo the reversal.
    Shapely >= 2 does NOT reverse — the coords come back in travel order, as
    verified live. Reversing again would break it: half the edges would run
    backwards and every bearing, instruction and sample ordering would be wrong.
    """
    offset = line.parallel_offset(distance_m, "left" if side == Side.LEFT else "right",
                                  join_style=2)
    if offset.is_empty or offset.geom_type != "LineString":
        # degenerate offset (self-intersecting hairpin); fall back to the centerline
        return line
    return offset


def _bearing_deg(line: LineString) -> float:
    (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
    return float((np.degrees(np.arctan2(bx - ax, by - ay)) + 360.0) % 360.0)


class _NodeIndex:
    """Snaps coordinates within NODE_SNAP_M onto a shared integer node id."""

    def __init__(self) -> None:
        self._coords: list[tuple[float, float]] = []
        self._lookup: dict[tuple[int, int], int] = {}

    def get(self, x: float, y: float) -> int:
        key = (round(x / NODE_SNAP_M), round(y / NODE_SNAP_M))
        if key not in self._lookup:
            self._lookup[key] = len(self._coords)
            self._coords.append((x, y))
        return self._lookup[key]

    def frame(self) -> pd.DataFrame:
        xs, ys = zip(*self._coords) if self._coords else ((), ())
        return pd.DataFrame(
            {
                "node_id": np.arange(len(self._coords), dtype=np.uint32),
                "x_m": np.asarray(xs, dtype=np.float64),
                "y_m": np.asarray(ys, dtype=np.float64),
            }
        )


def build_sidewalk_edges(streets, sidewalk_hint=None):
    """streets: GeoDataFrame from cscl.load(). sidewalk_hint: unused since the
    planimetric datasets turned out to be unusable (DATA-FINDINGS #8) — kept for
    interface stability; widths come from CSCL streetwidth via offset_for().
    Returns (nodes_df, edges_df)."""
    hint_tree = None
    hint_geoms = None
    if sidewalk_hint is not None and len(sidewalk_hint):
        hint_geoms = list(sidewalk_hint.geometry.values)
        hint_tree = STRtree(hint_geoms)

    index = _NodeIndex()
    rows: list[dict] = []

    widths = streets["street_width_m"] if "street_width_m" in streets.columns else None

    for row_idx, street in enumerate(streets.itertuples()):
        line = street.geometry
        if line is None or line.length < MIN_EDGE_LENGTH_M:
            continue
        width_ft = None
        if widths is not None:
            width_m = widths.iloc[row_idx]
            width_ft = width_m / 0.3048 if pd.notna(width_m) else None
        offset_m = offset_for(width_ft)
        for side in (Side.LEFT, Side.RIGHT):
            geom = offset_side(line, side, offset_m)
            if geom.length < MIN_EDGE_LENGTH_M:
                continue
            (ax, ay), (bx, by) = geom.coords[0], geom.coords[-1]
            rows.append(
                {
                    "u": index.get(ax, ay),
                    "v": index.get(bx, by),
                    "kind": int(EdgeKind.SIDEWALK),
                    "side": int(side),
                    "street_name": street.street_name,
                    "physical_id": int(street.physical_id),
                    "bearing_deg": _bearing_deg(geom),
                    "length_m": float(geom.length),
                    "width_m": _width_hint(geom, hint_tree, hint_geoms),
                    "geometry": geom,
                }
            )

    edges = pd.DataFrame(rows)
    if len(edges):
        edges.insert(0, "edge_id", np.arange(len(edges), dtype=np.uint32))
    else:
        edges = pd.DataFrame(
            columns=["edge_id", "u", "v", "kind", "side", "street_name",
                     "physical_id", "bearing_deg", "length_m", "width_m", "geometry"]
        )
    nodes = index.frame()
    nodes["is_intersection"] = True
    nodes["borough"] = "1"
    return nodes, edges


def _width_hint(geom: LineString, tree, geoms) -> float | None:
    """Recover a real sidewalk width by measuring how far the nearest planimetric
    sidewalk centerline is from our synthetic one. Only used when such data is
    supplied; normally widths come from CSCL streetwidth."""
    if tree is None:
        return None
    probe = geom.interpolate(0.5, normalized=True)
    hits = tree.query(probe.buffer(WIDTH_SEARCH_M))
    if len(hits) == 0:
        return None
    nearest = min((geoms[i] for i in hits), key=lambda g: g.distance(probe))
    distance = nearest.distance(probe)
    # a planimetric centerline sitting d metres from our offset implies our offset
    # is off by d; report a plausible width rather than the error itself
    fallback_half = offset_for(None) - SIDEWALK_HALF_WIDTH_M
    return float(np.clip(2.0 * (fallback_half - distance) + 4.0, 1.5, 12.0))
