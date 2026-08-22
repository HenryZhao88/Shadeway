import json
from pathlib import Path

import numpy as np
import pytest

from shadeway.thermal import utci

GOLDEN = json.loads((Path(__file__).with_name("golden_utci.json")).read_text())


def test_golden_file_was_actually_filled_in():
    assert GOLDEN["cases"], "add reference cases from utci.org"
    assert all(c["utci_c"] is not None for c in GOLDEN["cases"]), (
        "every golden case needs a reference value — do not guess them"
    )
    assert "<DATE>" not in GOLDEN["source"]


@pytest.mark.parametrize("case", GOLDEN["cases"])
def test_matches_published_reference(case):
    got = utci.utci_c(
        case["air_temp_c"], case["tmrt_c"], case["wind_10m_ms"], case["rh_pct"]
    )
    assert abs(got - case["utci_c"]) < 0.1, f"{got} vs published {case['utci_c']}"


def test_hotter_tmrt_gives_a_hotter_feels_like():
    cool = utci.utci_c(30.0, 30.0, 2.0, 50.0)
    hot = utci.utci_c(30.0, 65.0, 2.0, 50.0)
    assert hot - cool > 5.0


def test_more_wind_feels_cooler_when_it_is_hot():
    still = utci.utci_c(32.0, 55.0, 0.6, 45.0)
    breezy = utci.utci_c(32.0, 55.0, 5.0, 45.0)
    assert breezy < still


def test_the_shadeway_headline_is_reproducible():
    """A sunny sidewalk vs a shaded one on the same hot afternoon should differ
    by roughly the magnitude we put on stage."""
    sunny = utci.utci_c(30.6, 62.0, 2.0, 48.0)
    shaded = utci.utci_c(30.6, 34.0, 2.0, 48.0)
    assert 4.0 < sunny - shaded < 15.0


def test_lookup_table_matches_the_polynomial():
    table = utci.UtciTable.build(
        air_temp_c=30.6, wind_10m_ms=2.0, relative_humidity_pct=48.0
    )
    probe = np.linspace(-10.0, 80.0, 400)
    direct = utci.utci_c_vec(30.6, probe, 2.0, 48.0)
    assert np.max(np.abs(table.lookup(probe) - direct)) < 0.05


def test_lookup_table_is_much_faster_than_the_polynomial():
    import time

    probe = np.random.default_rng(0).uniform(10.0, 70.0, 20000)
    table = utci.UtciTable.build(30.6, 2.0, 48.0)

    t0 = time.perf_counter()
    utci.utci_c_vec(30.6, probe, 2.0, 48.0)
    poly_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    table.lookup(probe)
    table_s = time.perf_counter() - t0

    assert table_s * 5 < poly_s, f"table {table_s*1e3:.2f}ms vs poly {poly_s*1e3:.2f}ms"


def test_wind_is_reduced_from_ten_metres_to_pedestrian_height():
    reduced = utci.wind_at_pedestrian_height(5.0)
    assert 1.5 < float(reduced) < 5.0, "1.1 m wind is meaningfully slower than 10 m wind"


def test_inputs_outside_the_published_validity_range_are_clamped_not_extrapolated():
    extreme = utci.utci_c(30.0, 200.0, 2.0, 50.0)
    clamped = utci.utci_c(
        30.0, 30.0 + utci.VALIDITY["delta_tmrt_c"][1], 2.0, 50.0
    )
    assert abs(extreme - clamped) < 1e-6
