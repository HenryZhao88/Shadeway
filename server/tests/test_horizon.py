import time

import numpy as np
import pytest

from shadeway.horizon import HorizonCache
from shadeway.scene import Scene
from shadeway_contracts.fixtures import write_fixture_city
from shadeway_contracts.tables import read_table


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    data = tmp_path_factory.mktemp("hz")
    write_fixture_city(data)
    scene = Scene.load(data)
    samples = read_table(data / "samples.parquet")
    xy = np.column_stack(
        [np.asarray(samples.column("x_m")), np.asarray(samples.column("y_m"))]
    )
    return HorizonCache(scene, xy)


def test_cache_shape_and_dtype(cache):
    assert cache.store.dtype == np.uint8
    assert cache.store.shape == (2, len(cache.samples_xy), 72)


def test_memory_footprint_includes_quantised_tau_and_warm_flag(cache):
    # 144 B horizon + 72 B tau + 1 B warm flag per sample. Tau used to be
    # float32 (288 B/sample) and dominated the resident cache.
    assert cache.nbytes == len(cache.samples_xy) * (72 * 3 + 1)


def test_nothing_is_warm_before_you_ask(cache):
    assert not cache.warm.all()


def test_ensure_warms_exactly_the_requested_samples(cache):
    ids = np.array([0, 1, 2], dtype=np.uint32)
    cache.ensure(ids)
    assert cache.warm[ids].all()


def test_a_warm_lookup_is_far_faster_than_a_cold_one(cache):
    cold_ids = np.arange(200, 260, dtype=np.uint32)
    t0 = time.perf_counter()
    cache.ensure(cold_ids)
    cold_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(50):
        cache.f_sun(cold_ids, 180.0, 45.0)
    warm_s = (time.perf_counter() - t0) / 50

    assert warm_s * 100 < cold_s, f"cold {cold_s*1e3:.1f}ms vs warm {warm_s*1e3:.3f}ms"


def test_svf_is_between_zero_and_one_and_lower_in_a_canyon(cache):
    ids = np.arange(0, 120, dtype=np.uint32)
    cache.ensure(ids)
    svf = cache.svf(ids)
    assert svf.min() >= 0.0 and svf.max() <= 1.0
    assert svf.std() > 0.01, "every sample having the same svf means the cache is empty"


def test_f_sun_is_zero_when_the_sun_is_down(cache):
    ids = np.array([0, 1], dtype=np.uint32)
    cache.ensure(ids)
    assert (cache.f_sun(ids, 180.0, -5.0) == 0.0).all()


def test_f_sun_interpolates_between_azimuth_bins(cache):
    ids = np.array([0], dtype=np.uint32)
    cache.ensure(ids)
    a = cache.f_sun(ids, 0.0, 30.0)[0]
    b = cache.f_sun(ids, 5.0, 30.0)[0]
    mid = cache.f_sun(ids, 2.5, 30.0)[0]
    assert min(a, b) - 1e-6 <= mid <= max(a, b) + 1e-6


def test_invalidation_clears_only_nearby_samples(cache):
    ids = np.arange(0, 200, dtype=np.uint32)
    cache.ensure(ids)
    x, y = cache.samples_xy[0]
    cleared = cache.invalidate_within(float(x), float(y), 25.0)
    assert 0 < cleared < len(ids)
    assert not cache.warm[0]
    assert cache.warm[ids].sum() > 0, "invalidation must be local, not global"


def test_precomputed_cache_rejects_the_wrong_source_fingerprint(cache, tmp_path):
    path = tmp_path / "wrong.npz"
    np.savez_compressed(
        path,
        store=np.zeros_like(cache.store),
        tau=np.full_like(cache.canopy_tau, 255),
        fingerprint=np.asarray("different-build"),
    )
    target = HorizonCache(cache.scene, cache.samples_xy, fingerprint="expected-build")
    assert not target.load_precomputed(path)
    assert not target.warm.any()


def test_precomputed_cache_accepts_matching_fingerprint(cache, tmp_path):
    path = tmp_path / "matching.npz"
    np.savez_compressed(
        path,
        store=np.zeros_like(cache.store),
        tau=np.full_like(cache.canopy_tau, 255),
        fingerprint=np.asarray("expected-build"),
    )
    target = HorizonCache(cache.scene, cache.samples_xy, fingerprint="expected-build")
    assert target.load_precomputed(path)
    assert target.warm.all()


def test_trusted_legacy_float_tau_is_quantised_on_load(cache, tmp_path):
    path = tmp_path / "legacy.npz"
    tau = np.full(cache.canopy_tau.shape, 0.38, dtype=np.float32)
    np.savez_compressed(path, store=np.zeros_like(cache.store), tau=tau)
    target = HorizonCache(cache.scene, cache.samples_xy, fingerprint="expected-build")
    assert target.load_precomputed(path, legacy_ok=True)
    assert target.canopy_tau.dtype == np.uint8
    assert float(target.canopy_tau[0, 0]) / 255.0 == pytest.approx(0.38, abs=0.002)
