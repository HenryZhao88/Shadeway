import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from shadeway_pipeline.config import SCOPES, TARGET_CRS
from shadeway_pipeline.sources import buildings, cscl


@pytest.fixture()
def fake_cscl_geojson(tmp_path, monkeypatch):
    """Two crossing segments in Manhattan, in WGS84 — as Socrata actually serves it."""
    frame = gpd.GeoDataFrame(
        {
            "physicalid": ["101", "102"],
            "full_street_name": ["5 AVENUE", "W 42 STREET"],
            "boroughcode": ["1", "1"],
            "rw_type": ["1", "1"],
            "streetwidth": ["70", "30"],
            "geometry": [
                LineString([(-73.9850, 40.7500), (-73.9850, 40.7590)]),
                LineString([(-73.9900, 40.7545), (-73.9800, 40.7545)]),
            ],
        },
        crs="EPSG:4326",
    )
    path = tmp_path / "cscl.geojson"
    frame.to_file(path, driver="GeoJSON")
    monkeypatch.setattr(cscl, "PREFETCHED", path)
    return path


def test_cscl_reprojects_to_metres(fake_cscl_geojson):
    frame = cscl.load(SCOPES["midtown"])
    assert frame.crs.to_string() == TARGET_CRS
    # ~1000 m of latitude in the source stays ~1000 m (not feet-inflated)
    assert 900.0 < frame.geometry.iloc[0].length < 1100.0


def test_cscl_normalises_columns_and_keeps_width(fake_cscl_geojson):
    frame = cscl.load(SCOPES["midtown"])
    for col in ("physical_id", "street_name", "borough", "street_width_m", "geometry"):
        assert col in frame.columns
    assert frame["physical_id"].dtype.kind == "i"
    assert frame["street_name"].iloc[0] == "5 Avenue"  # title-cased for the UI
    # streetwidth arrives in FEET; the loader converts to metres
    assert abs(frame["street_width_m"].iloc[0] - 70 * 0.3048) < 0.01


def test_cscl_filters_non_walkable_and_other_boroughs(tmp_path, monkeypatch):
    frame = gpd.GeoDataFrame(
        {
            "physicalid": ["1", "2", "3"],
            "full_street_name": ["A", "B", "C"],
            "boroughcode": ["1", "5", "1"],
            "rw_type": ["1", "1", "2"],  # rw_type 2 = highway, not walkable
            "geometry": [
                LineString([(-73.985, 40.75), (-73.984, 40.75)]),
                LineString([(-74.10, 40.64), (-74.09, 40.64)]),
                LineString([(-73.984, 40.76), (-73.983, 40.76)]),
            ],
        },
        crs="EPSG:4326",
    )
    path = tmp_path / "cscl2.geojson"
    frame.to_file(path, driver="GeoJSON")
    monkeypatch.setattr(cscl, "PREFETCHED", path)
    out = cscl.load(SCOPES["manhattan"])
    assert len(out) == 1


def test_buildings_height_is_metres_and_positive(tmp_path, monkeypatch):
    frame = gpd.GeoDataFrame(
        {
            "bin": ["1000001", "1000002"],
            "height_roof": [328.084, 0.0],  # feet: 100 m, and a bad zero-height row
            "ground_elevation": [0.0, 0.0],
            "feature_code": ["2100", "2100"],
            "geometry": [
                Polygon([(-73.9850, 40.7500), (-73.9848, 40.7500),
                         (-73.9848, 40.7502), (-73.9850, 40.7502)]),
                Polygon([(-73.9840, 40.7500), (-73.9838, 40.7500),
                         (-73.9838, 40.7502), (-73.9840, 40.7502)]),
            ],
        },
        crs="EPSG:4326",
    )
    path = tmp_path / "bldg.geojson"
    frame.to_file(path, driver="GeoJSON")
    monkeypatch.setattr(buildings, "PREFETCHED", {"1": path})

    loaded = buildings.load(SCOPES["midtown"])
    assert len(loaded) == 1, "zero-height buildings must be dropped, they cast no shade"
    assert 99.0 < loaded["height_m"].iloc[0] < 101.0


def test_buildings_drop_non_building_feature_codes(tmp_path, monkeypatch):
    frame = gpd.GeoDataFrame(
        {
            "bin": ["1000001", "1000002"],
            "height_roof": [100.0, 100.0],
            "feature_code": ["2100", "9999"],  # 9999 = something else entirely
            "geometry": [
                Polygon([(-73.9850, 40.7500), (-73.9848, 40.7500),
                         (-73.9848, 40.7502), (-73.9850, 40.7502)]),
                Polygon([(-73.9840, 40.7500), (-73.9838, 40.7500),
                         (-73.9838, 40.7502), (-73.9840, 40.7502)]),
            ],
        },
        crs="EPSG:4326",
    )
    path = tmp_path / "bldg2.geojson"
    frame.to_file(path, driver="GeoJSON")
    monkeypatch.setattr(buildings, "PREFETCHED", {"1": path})
    assert len(buildings.load(SCOPES["midtown"])) == 1


def test_every_borough_in_scope_gets_a_building_source(monkeypatch, tmp_path):
    """A multi-borough scope that is only half prefetched must download the
    rest, not quietly build a city with half its occluders missing."""
    from shadeway_pipeline.config import SCOPES
    from shadeway_pipeline.sources import buildings

    manhattan = tmp_path / "buildings_manhattan.geojson"
    manhattan.write_text("{}")
    monkeypatch.setattr(
        buildings, "PREFETCHED", {"1": manhattan, "3": tmp_path / "absent.geojson"}
    )

    requested: list[str] = []

    def fake_download(dataset_id, where=None, **_):
        requested.append(where or "")
        return tmp_path / f"downloaded_{len(requested)}.geojson"

    monkeypatch.setattr(buildings, "socrata_geojson", fake_download)
    monkeypatch.setattr(buildings, "load_datasets", lambda: {"buildings": "abcd-1234"})

    paths = buildings._download(SCOPES["manhattan_brooklyn"])

    assert len(paths) == 2, "one source per borough in the scope"
    assert manhattan in paths
    assert len(requested) == 1, "only the missing borough should be downloaded"
    assert "3000000" in requested[0], "Brooklyn's BIN range was not requested"


def test_an_unknown_borough_code_fails_loudly(monkeypatch, tmp_path):
    from shadeway_pipeline.config import Scope
    from shadeway_pipeline.sources import buildings

    monkeypatch.setattr(buildings, "PREFETCHED", {})
    scope = Scope("odd", ["9"], (-74.0, 40.7, -73.9, 40.8))
    with pytest.raises(ValueError, match="BIN range"):
        buildings._download(scope)


def test_trees_survive_an_export_with_no_species_column():
    """spc_latin drives tau. Losing it should degrade to unknown species, not
    take the whole build down."""
    import pandas as pd

    from shadeway_pipeline.sources import trees

    frame = pd.DataFrame({"tree_dbh": [10, 20]})
    species = trees._text_column(frame, "spc_latin")
    assert list(species) == ["", ""]


def test_trees_keep_species_when_the_column_is_present():
    import pandas as pd

    from shadeway_pipeline.sources import trees

    frame = pd.DataFrame({"spc_latin": ["Gleditsia triacanthos", None]})
    assert list(trees._text_column(frame, "spc_latin")) == [
        "Gleditsia triacanthos",
        "",
    ]
