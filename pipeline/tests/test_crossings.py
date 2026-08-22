import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from shadeway_contracts.tables import EdgeKind, Side
from shadeway_pipeline.config import TARGET_CRS
from shadeway_pipeline.graph import build, crossings


def _cross_intersection() -> gpd.GeoDataFrame:
    """A plus sign: four street stubs meeting at the origin."""
    return gpd.GeoDataFrame(
        {
            "physical_id": [1, 2, 3, 4],
            "street_name": ["N", "S", "E", "W"],
            "borough": ["1"] * 4,
            "street_width_m": [30 * 0.3048] * 4,
            "geometry": [
                LineString([(0.0, 0.0), (0.0, 60.0)]),
                LineString([(0.0, 0.0), (0.0, -60.0)]),
                LineString([(0.0, 0.0), (60.0, 0.0)]),
                LineString([(0.0, 0.0), (-60.0, 0.0)]),
            ],
        },
        crs=TARGET_CRS,
    )


def test_crossings_make_the_intersection_connected():
    nodes, edges = build.build_sidewalk_edges(_cross_intersection(), None)
    before = crossings.connectivity_report(nodes, edges)
    nodes2, edges2 = crossings.add_crossings(nodes, edges)
    after = crossings.connectivity_report(nodes2, edges2)
    assert after["n_components"] < before["n_components"]
    assert after["n_components"] == 1


def test_crossings_are_marked_and_have_no_side():
    nodes, edges = build.build_sidewalk_edges(_cross_intersection(), None)
    _, edges2 = crossings.add_crossings(nodes, edges)
    added = edges2[edges2["kind"] == EdgeKind.CROSSING]
    assert len(added) > 0
    assert set(added["side"]) == {int(Side.NONE)}


def test_absurdly_long_crossings_are_refused():
    """Two sidewalk stubs 300 m apart are not a crosswalk."""
    far = gpd.GeoDataFrame(
        {
            "physical_id": [1, 2],
            "street_name": ["A", "B"],
            "borough": ["1", "1"],
            "street_width_m": [np.nan, np.nan],
            "geometry": [
                LineString([(0.0, 0.0), (0.0, 60.0)]),
                LineString([(300.0, 0.0), (300.0, 60.0)]),
            ],
        },
        crs=TARGET_CRS,
    )
    nodes, edges = build.build_sidewalk_edges(far, None)
    _, edges2 = crossings.add_crossings(nodes, edges)
    assert (edges2["kind"] == EdgeKind.CROSSING).sum() == 0


def test_edge_ids_stay_unique_and_contiguous():
    nodes, edges = build.build_sidewalk_edges(_cross_intersection(), None)
    _, edges2 = crossings.add_crossings(nodes, edges)
    assert list(edges2["edge_id"]) == list(range(len(edges2)))


def test_crossing_endpoints_reference_real_nodes():
    nodes, edges = build.build_sidewalk_edges(_cross_intersection(), None)
    nodes2, edges2 = crossings.add_crossings(nodes, edges)
    valid = set(nodes2["node_id"])
    assert set(edges2["u"]) <= valid
    assert set(edges2["v"]) <= valid


def test_connectivity_report_shape():
    nodes, edges = build.build_sidewalk_edges(_cross_intersection(), None)
    report = crossings.connectivity_report(nodes, edges)
    assert set(report) == {"n_components", "largest_component_fraction", "orphan_nodes"}
    assert 0.0 < report["largest_component_fraction"] <= 1.0
