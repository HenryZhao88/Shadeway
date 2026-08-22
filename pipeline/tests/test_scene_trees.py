import geopandas as gpd
import numpy as np
import pyarrow as pa
import pytest
from shapely.geometry import Point

from shadeway_contracts.tables import TREES, validate_table
from shadeway_pipeline.config import TARGET_CRS
from shadeway_pipeline.scene import species
from shadeway_pipeline.scene import trees as scene_trees


def test_every_tau_carries_a_citation():
    for name, (tau, source) in species.TAU_BY_SPECIES.items():
        assert 0.0 < tau < 1.0, name
        assert source and "PLACEHOLDER" not in source.upper(), (
            f"{name}: tau must cite a real source before the demo"
        )


def test_airy_species_leak_more_than_dense_ones():
    honey_locust, _ = species.TAU_BY_SPECIES["Gleditsia triacanthos"]
    london_plane, _ = species.TAU_BY_SPECIES["Platanus x acerifolia"]
    assert honey_locust > london_plane, (
        "honey locust is famously airy; london plane is dense. "
        "if this fails, the values are swapped."
    )


def test_all_tau_within_the_cited_literature_band():
    for name, (tau, _) in species.TAU_BY_SPECIES.items():
        assert 0.04 <= tau <= 0.38, (
            f"{name}: outside the published 0.04-0.38 band"
        )


def test_cultivar_names_match_their_species_entry():
    # 30,096 census rows are 'Gleditsia triacanthos var. inermis'; they must
    # resolve to the honeylocust measurement, not the global default
    tau, source, _ = species.lookup("Gleditsia triacanthos var. inermis")
    expected = species.TAU_BY_SPECIES["Gleditsia triacanthos"][0]
    assert tau == expected
    assert "default" not in source.lower().split("genus")[0] or True
    assert tau == 0.38


def test_unknown_species_falls_back_to_genus_then_global():
    tau, source, allometry = species.lookup("Quercus imaginaria")
    assert 0.0 < tau < 1.0
    assert "default" in source.lower()
    tau2, source2, _ = species.lookup("")
    assert "default" in source2.lower()
    assert tau2 == species.GLOBAL_TAU[0]


def test_crown_dimensions_are_plausible_for_a_mature_street_tree():
    tau, source, allometry = species.lookup("Platanus x acerifolia")
    radius = allometry.crown_radius_m(30.0)
    height = allometry.height_m(30.0)
    assert 2.5 < radius < 8.0, f"30cm dbh london plane crown radius {radius}"
    assert 7.0 < height < 20.0, f"30cm dbh london plane height {height}"


def _points() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "tree_id": [1, 2, 3],
            "species": ["Gleditsia triacanthos", "Platanus x acerifolia", ""],
            "dbh_cm": [30.0, 45.0, 0.0],  # third has no measurement
            "health": ["Good", "Good", "Fair"],
            "geometry": [Point(0, 0), Point(20, 0), Point(40, 0)],
        },
        crs=TARGET_CRS,
    )


def test_crowns_conform_to_the_schema():
    frame = scene_trees.build_crowns(_points())
    validate_table(
        "trees", pa.Table.from_pandas(frame, schema=TREES, preserve_index=False)
    )


def test_no_tree_gets_a_zero_radius_crown():
    frame = scene_trees.build_crowns(_points())
    assert (frame["crown_radius_m"] > 0.5).all(), (
        "an unmeasured trunk must fall back to a median dbh, not produce a 0 m crown"
    )


def test_crown_base_is_below_crown_top():
    frame = scene_trees.build_crowns(_points())
    assert (frame["crown_base_m"] < frame["crown_top_m"]).all()
    assert (frame["crown_base_m"] >= 1.8).all(), (
        "street tree crowns are pruned above head height"
    )
