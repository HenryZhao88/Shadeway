"""Production verification must enforce the same cache identity as runtime."""

import importlib.util
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from shadeway.horizon import source_fingerprint
from shadeway_contracts.fixtures import write_fixture_city

_spec = importlib.util.spec_from_file_location(
    "verify_city", Path(__file__).resolve().parents[2] / "deploy" / "verify_city.py"
)
verify_city = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_city)


@pytest.fixture()
def city(tmp_path, monkeypatch):
    write_fixture_city(tmp_path)
    monkeypatch.setattr(verify_city, "MIN_PRODUCTION_EDGES", 1)
    samples = pq.read_metadata(tmp_path / "samples.parquet").num_rows
    np.savez_compressed(
        tmp_path / "horizon.npz",
        store=np.zeros((2, samples, 72), dtype=np.uint8),
        tau=np.full((samples, 72), 255, dtype=np.uint8),
        fingerprint=np.asarray(source_fingerprint(tmp_path)),
    )
    return tmp_path


def test_matching_city_and_horizon_are_accepted(city):
    edges, samples = verify_city.verify(city)
    assert edges > 0 and samples > 0


def test_mismatched_scene_is_rejected_even_when_cache_shapes_match(city):
    # Changing metadata preserves every row and cache dimension, but gives the
    # artifact a different source identity, just like a rebuild.
    table = pq.read_table(city / "trees.parquet")
    pq.write_table(table.replace_schema_metadata({b"build": b"changed"}), city / "trees.parquet")
    with pytest.raises(ValueError, match="fingerprint"):
        verify_city.verify(city)
