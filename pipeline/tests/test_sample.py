import numpy as np
import pandas as pd
from shapely.geometry import LineString

from shadeway_contracts.tables import SAMPLE_SPACING_M
from shadeway_pipeline.graph import sample
from shadeway_pipeline.sources import landcover


def _edges() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "edge_id": np.array([0, 1], dtype=np.uint32),
            "length_m": [100.0, 3.0],
            "geometry": [
                LineString([(0.0, 0.0), (100.0, 0.0)]),
                LineString([(0.0, 50.0), (3.0, 50.0)]),
            ],
        }
    )


def test_a_hundred_metre_edge_gets_eleven_samples():
    edges, samples = sample.add_samples(_edges())
    assert int(edges.loc[0, "sample_count"]) == 11  # 0,10,...,100 inclusive


def test_a_short_edge_still_gets_both_endpoints():
    edges, samples = sample.add_samples(_edges())
    assert int(edges.loc[1, "sample_count"]) == 2


def test_spacing_never_exceeds_the_contract():
    edges, samples = sample.add_samples(_edges())
    for row in edges.itertuples():
        block = samples.iloc[row.sample_start : row.sample_start + row.sample_count]
        step = np.hypot(np.diff(block["x_m"]), np.diff(block["y_m"]))
        assert step.max() <= SAMPLE_SPACING_M + 0.5


def test_sample_ranges_tile_exactly():
    edges, samples = sample.add_samples(_edges())
    covered = np.zeros(len(samples), dtype=bool)
    for row in edges.itertuples():
        sl = slice(row.sample_start, row.sample_start + row.sample_count)
        assert not covered[sl].any()
        covered[sl] = True
    assert covered.all()


def test_samples_run_from_u_to_v():
    edges, samples = sample.add_samples(_edges())
    block = samples.iloc[0 : int(edges.loc[0, "sample_count"])]
    assert block["x_m"].is_monotonic_increasing
    assert block["t"].iloc[0] == 0.0
    assert block["t"].iloc[-1] == 1.0


def test_every_sample_has_an_albedo():
    edges, samples = sample.add_samples(_edges())
    assert samples["ground_albedo"].between(0.01, 0.95).all()
    assert samples["landcover_class"].notna().all()


def test_albedo_table_covers_every_landcover_class():
    assert set(landcover.CLASS_ALBEDO) == set(range(1, 8)), "the 2010 raster has 7 classes"
    assert all(0.02 <= a <= 0.9 for a in landcover.CLASS_ALBEDO.values())


def test_albedo_falls_back_to_a_default_when_the_raster_is_missing(monkeypatch):
    monkeypatch.setattr(landcover, "_open_raster", lambda: None)
    monkeypatch.setattr(landcover, "_to_raster_crs", lambda: None)
    albedo, classes = landcover.albedo_at(np.array([300000.0]), np.array([60000.0]))
    assert albedo.shape == (1,)
    assert 0.05 < albedo[0] < 0.4
    assert classes[0] == landcover.DEFAULT_CLASS
