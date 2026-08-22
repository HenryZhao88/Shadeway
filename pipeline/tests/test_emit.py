import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from shadeway_contracts.tables import ALL_TABLES, read_table, validate_table
from shadeway_pipeline import emit
from shadeway_pipeline.config import SCOPES, TARGET_CRS


@pytest.fixture()
def tiny_city(monkeypatch):
    """Patch every source loader so emit.build_tables() runs with no network."""
    streets = gpd.GeoDataFrame(
        {
            "physical_id": [1, 2],
            "street_name": ["5 Avenue", "W 42 Street"],
            "borough": ["1", "1"],
            "street_width_m": [70 * 0.3048, 30 * 0.3048],
            "geometry": [
                LineString([(301266.8, 64776.9), (301266.8, 64896.9)]),
                LineString([(301266.8, 64776.9), (301386.8, 64776.9)]),
            ],
        },
        crs=TARGET_CRS,
    )
    buildings = gpd.GeoDataFrame(
        {
            "building_id": [0],
            "height_m": [90.0],
            "base_m": [0.0],
            "geometry": [Polygon([(301300, 64796), (301360, 64796),
                                  (301360, 64856), (301300, 64856)])],
        },
        crs=TARGET_CRS,
    )
    trees = gpd.GeoDataFrame(
        {
            "tree_id": [1],
            "species": ["Gleditsia triacanthos"],
            "dbh_cm": [30.0],
            "health": ["Good"],
            "geometry": [Point(301260.0, 647816.9)],
        },
        crs=TARGET_CRS,
    )
    amenities = gpd.GeoDataFrame(
        {"kind": [0], "name": ["Fountain"], "geometry": [Point(301276.8, 647796.9)]},
        crs=TARGET_CRS,
    )
    monkeypatch.setattr(emit.cscl, "load", lambda scope: streets)
    monkeypatch.setattr(emit.buildings_src, "load", lambda scope: buildings)
    monkeypatch.setattr(emit.trees_src, "load", lambda scope: trees)
    monkeypatch.setattr(emit.amenities_src, "load", lambda scope: amenities)


def test_build_produces_every_table(tiny_city):
    tables = emit.build_tables(SCOPES["midtown"])
    assert set(tables) == set(ALL_TABLES)
    for name, table in tables.items():
        validate_table(name, table)


def test_write_round_trips_through_parquet(tiny_city, tmp_path):
    emit.write(emit.build_tables(SCOPES["midtown"]), tmp_path)
    for name in ALL_TABLES:
        assert read_table(tmp_path / f"{name}.parquet").num_rows >= 0


def test_nodes_get_lonlat_for_the_api_boundary(tiny_city):
    tables = emit.build_tables(SCOPES["midtown"])
    lons = tables["nodes"].column("lon").to_pylist()
    lats = tables["nodes"].column("lat").to_pylist()
    assert all(-75 < v < -73 for v in lons)
    assert all(40 < v < 41 for v in lats)
