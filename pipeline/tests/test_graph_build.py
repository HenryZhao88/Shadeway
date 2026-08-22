import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from shadeway_contracts.tables import EdgeKind, Side
from shadeway_pipeline.config import TARGET_CRS
from shadeway_pipeline.graph import build


def _streets() -> gpd.GeoDataFrame:
    """An L: one segment north, one segment east, sharing a corner."""
    return gpd.GeoDataFrame(
        {
            "physical_id": [1, 2],
            "street_name": ["5 Avenue", "W 42 Street"],
            "borough": ["1", "1"],
            "street_width_m": [70 * 0.3048, 30 * 0.3048],
            "geometry": [
                LineString([(0.0, 0.0), (0.0, 100.0)]),
                LineString([(0.0, 0.0), (100.0, 0.0)]),
            ],
        },
        crs=TARGET_CRS,
    )


def test_offset_left_is_west_of_a_northbound_line():
    line = LineString([(0.0, 0.0), (0.0, 100.0)])  # heading north
    left = build.offset_side(line, Side.LEFT, 6.0)
    assert left.coords[0][0] < 0, "left of northbound travel is west (negative x)"
    right = build.offset_side(line, Side.RIGHT, 6.0)
    assert right.coords[0][0] > 0


def test_offset_preserves_direction_of_travel():
    line = LineString([(0.0, 0.0), (0.0, 100.0)])
    for side in (Side.LEFT, Side.RIGHT):
        offset = build.offset_side(line, side, 6.0)
        assert offset.coords[-1][1] > offset.coords[0][1], (
            "shapely's parallel_offset reverses right-hand offsets; undo it"
        )


def test_every_street_yields_exactly_two_sidewalks():
    nodes, edges = build.build_sidewalk_edges(_streets(), None)
    sidewalks = edges[edges["kind"] == EdgeKind.SIDEWALK]
    assert len(sidewalks) == 4
    per_parent = sidewalks.groupby("physical_id")["side"].apply(set)
    assert all(s == {int(Side.LEFT), int(Side.RIGHT)} for s in per_parent)


def test_shared_corners_yield_one_node_per_stub_end():
    """Both streets meet at (0,0). The four sidewalk stubs end near that corner
    at their own offsets — avenue sidewalks at |x|=12.7 m, street sidewalks at
    |y|=6.6 m — which 1 m snapping cannot and should not merge. Joining them
    across the intersection is Task 5's job (synthesised crossings); here we
    assert each stub got its own node and nothing was duplicated or dropped.
    """
    nodes, edges = build.build_sidewalk_edges(_streets(), None)
    assert len(edges) == 4
    assert len(nodes) == 8  # 2 endpoints x 4 stubs
    corner_keys = {(round(x), round(y)) for x, y in
                   [(0, 0), (12.67, 0), (-12.67, 0), (0, 6.57), (0, -6.57)]}
    ends = [(round(n.x_m), round(n.y_m)) for n in nodes.itertuples()
            if abs(n.x_m) < 20 and abs(n.y_m) < 20]
    assert len(ends) == 4, "four distinct corner-end nodes near the origin"
    assert all(e in corner_keys for e in ends)


def test_bearing_is_compass_degrees_from_north():
    nodes, edges = build.build_sidewalk_edges(_streets(), None)
    north = edges[edges["street_name"] == "5 Avenue"]["bearing_deg"].iloc[0]
    east = edges[edges["street_name"] == "W 42 Street"]["bearing_deg"].iloc[0]
    assert abs(north - 0.0) < 1.0 or abs(north - 360.0) < 1.0
    assert abs(east - 90.0) < 1.0


def test_degenerate_slivers_are_dropped():
    tiny = gpd.GeoDataFrame(
        {
            "physical_id": [9],
            "street_name": ["Sliver"],
            "borough": ["1"],
            "street_width_m": [np.nan],
            "geometry": [LineString([(0.0, 0.0), (0.5, 0.0)])],
        },
        crs=TARGET_CRS,
    )
    nodes, edges = build.build_sidewalk_edges(tiny, None)
    assert len(edges) == 0


def test_wider_streets_get_larger_offsets():
    """The DATA-FINDINGS #7 win: a 70 ft avenue must separate its sidewalks more
    than a 30 ft side street does."""
    nodes, edges = build.build_sidewalk_edges(_streets(), None)
    # the avenue runs north, so its offset shows up as |x| of every vertex;
    # the side street runs east, so its offset shows up as |y|
    ave_offset = max(abs(x) for g in edges[edges["street_name"] == "5 Avenue"].geometry
                     for x, _ in g.coords)
    st_offset = max(abs(y) for g in edges[edges["street_name"] == "W 42 Street"].geometry
                    for _, y in g.coords)
    assert abs(ave_offset - 12.668) < 0.01   # 70 ft street
    assert abs(st_offset - 6.572) < 0.01     # 30 ft street


def test_width_hint_is_recovered_when_planimetric_data_is_nearby():
    hint = gpd.GeoDataFrame(
        {"geometry": [LineString([(-6.0, 0.0), (-6.0, 100.0)])]}, crs=TARGET_CRS
    )
    nodes, edges = build.build_sidewalk_edges(_streets(), hint)
    matched = edges[edges["width_m"].notna()]
    assert len(matched) >= 1
