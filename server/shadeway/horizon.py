"""The lazy horizon cache. This is why runtime ray casting is fast enough.

Layout: store[layer][sample_id][bin], uint8, 144 bytes per sample point,
plus canopy_tau[sample_id][bin], uint8, 72 bytes per sample point.
  layer 0 = opaque obstruction angle (buildings), degrees
  layer 1 = highest elevation at which canopy still intercepts, degrees
  bin b   = azimuth b * 5 degrees, 0 = north

Warming an entry costs a few ms (144 rays). Reading one is an array index.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

import numpy as np

from shadeway import occluder
from shadeway.scene import Scene

AZIMUTH_BINS = 72
BIN_WIDTH_DEG = 360.0 / AZIMUTH_BINS
LAYER_OPAQUE = 0
LAYER_CANOPY = 1
CACHE_FORMAT_VERSION = 2
FINGERPRINT_FILES = ("samples.parquet", "buildings.parquet", "trees.parquet")


def source_fingerprint(data_dir: Path) -> str:
    """Identity of every input that can change a horizon value."""
    digest = hashlib.sha256(f"shadeway-horizon-v{CACHE_FORMAT_VERSION}".encode())
    for name in FINGERPRINT_FILES:
        path = Path(data_dir) / name
        digest.update(name.encode())
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


class HorizonCache:
    def __init__(
        self,
        scene: Scene,
        samples_xy: np.ndarray,
        fingerprint: str | None = None,
    ) -> None:
        self.scene = scene
        self.samples_xy = np.asarray(samples_xy, dtype=np.float64)
        self.fingerprint = fingerprint
        n = len(self.samples_xy)
        self.store = np.zeros((2, n, AZIMUTH_BINS), dtype=np.uint8)
        self.warm = np.zeros(n, dtype=bool)
        # Tau is sourced to at best two decimal places. Quantising [0,1] into
        # uint8 has <= 0.002 absolute error and cuts this array from 150 MB to
        # 37.5 MB for Manhattan.
        self.canopy_tau = np.full((n, AZIMUTH_BINS), 255, dtype=np.uint8)
        self._sample_tree = None
        self._ensure_lock = threading.RLock()
        self._mapped_cache_dir: tempfile.TemporaryDirectory[str] | None = None

    @property
    def nbytes(self) -> int:
        return int(self.store.nbytes + self.canopy_tau.nbytes + self.warm.nbytes)

    def load_precomputed(self, path, *, legacy_ok: bool = False) -> bool:
        """Load a build-time warmed cache (`shadeway.warm --out`). Returns True
        on success. Store, quantised tau, and warm flags come along.
        Missing, stale, or shape-mismatched files are ignored, not fatal.

        `legacy_ok` permits the original cache format only when the caller has
        independently verified that the cache file is newer than every source
        parquet. New caches carry an exact source fingerprint."""
        mapped = self._load_mapped_current(Path(path))
        if mapped is not None:
            if mapped:
                self.warm[:] = True
            return mapped

        try:
            with np.load(path, allow_pickle=False) as data:
                store = data["store"]
                tau = data["tau"]
                encoded = (
                    str(data["fingerprint"].item())
                    if "fingerprint" in data.files
                    else None
                )
                if self.fingerprint is not None:
                    if encoded is None and not legacy_ok:
                        return False
                    if encoded is not None and encoded != self.fingerprint:
                        return False
                if store.shape != self.store.shape or tau.shape != self.canopy_tau.shape:
                    return False
                if store.dtype != np.uint8:
                    return False
                # npz members are ordinary writable ndarrays once decompressed.
                # Adopt current-format arrays directly instead of copying 112 MB
                # into the zero-filled placeholders allocated by __init__. This
                # keeps startup peak and steady RSS inside small hosts.
                self.store = store
                if tau.dtype == np.uint8:
                    self.canopy_tau = tau
                else:
                    if tau.dtype.kind not in {"f", "i", "u"}:
                        return False
                    # Read old float32 artifacts without forcing a multi-hour
                    # re-warm. Chunking keeps the conversion's peak RAM bounded.
                    for start in range(0, len(tau), 20_000):
                        block = np.asarray(tau[start : start + 20_000])
                        if not np.isfinite(block).all():
                            return False
                        self.canopy_tau[start : start + len(block)] = np.rint(
                            np.clip(block, 0.0, 1.0) * 255.0
                        ).astype(np.uint8)
        except Exception:
            return False
        self.warm[:] = True
        return True

    def _load_mapped_current(self, path: Path) -> bool | None:
        """Stream a v2 npz to disk and memory-map it without a RAM-sized copy.

        ``np.load`` must fully decompress members of a compressed npz. For the
        Manhattan cache that commits 112 MB immediately and briefly holds a
        second copy during startup. Extracting the contained ``.npy`` members
        as streams keeps startup bounded; copy-on-write maps still support the
        existing invalidation path when planting is enabled.

        ``None`` means this is a legacy artifact and should use the compatibility
        loader below. ``False`` means it claims to be current but is invalid.
        """
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            return False
        with archive:
            required = {"store.npy", "tau.npy", "fingerprint.npy"}
            if not required.issubset(archive.namelist()):
                return None
            mapped_dir = tempfile.TemporaryDirectory(prefix="shadeway-horizon-")
            root = Path(mapped_dir.name)
            try:
                for member in required:
                    target = root / member
                    with archive.open(member) as source, target.open("wb") as dest:
                        shutil.copyfileobj(source, dest, length=1024 * 1024)
                store = np.load(root / "store.npy", mmap_mode="c", allow_pickle=False)
                tau = np.load(root / "tau.npy", mmap_mode="c", allow_pickle=False)
                encoded = str(
                    np.load(root / "fingerprint.npy", allow_pickle=False).item()
                )
            except (OSError, TypeError, ValueError):
                mapped_dir.cleanup()
                return False

        valid = (
            store.shape == self.store.shape
            and tau.shape == self.canopy_tau.shape
            and store.dtype == np.uint8
            and tau.dtype == np.uint8
            and (self.fingerprint is None or encoded == self.fingerprint)
        )
        if not valid:
            mapped_dir.cleanup()
            return False
        self.store = store
        self.canopy_tau = tau
        self._mapped_cache_dir = mapped_dir
        return True

    def ensure(self, sample_ids: np.ndarray) -> None:
        ids = np.asarray(sample_ids, dtype=np.int64)
        if self.warm[ids].all():
            return
        # Multiple API reads may warm the same cold corridor concurrently.
        # Recheck under one lock so no caller observes a partially written bin.
        with self._ensure_lock:
            cold = ids[~self.warm[ids]]
            for sample_id in np.unique(cold):
                x, y = self.samples_xy[sample_id]
                self.store[LAYER_OPAQUE, sample_id] = (
                    occluder.building_horizon_profile(
                        self.scene, float(x), float(y), AZIMUTH_BINS
                    )
                )
                self.store[LAYER_CANOPY, sample_id] = (
                    occluder.canopy_horizon_profile(
                        self.scene, float(x), float(y), AZIMUTH_BINS
                    )
                )
                self.canopy_tau[sample_id] = np.rint(
                    self._tau_profile(float(x), float(y)) * 255.0
                ).astype(np.uint8)
                self.warm[sample_id] = True

    def _tau_profile(self, x: float, y: float) -> np.ndarray:
        """Tau product per azimuth bin, evaluated at a mid elevation."""
        return occluder.tau_profile(self.scene, x, y, 30.0, AZIMUTH_BINS)

    def _bin_lerp(self, layer: int, ids: np.ndarray, azimuth_deg: float):
        position = (azimuth_deg % 360.0) / BIN_WIDTH_DEG
        low = int(np.floor(position)) % AZIMUTH_BINS
        high = (low + 1) % AZIMUTH_BINS
        weight = position - np.floor(position)
        a = self.store[layer, ids, low].astype(np.float32)
        b = self.store[layer, ids, high].astype(np.float32)
        return a * (1.0 - weight) + b * weight, low, high, weight

    def f_sun(
        self, sample_ids: np.ndarray, azimuth_deg: float, elevation_deg: float
    ) -> np.ndarray:
        ids = np.asarray(sample_ids, dtype=np.int64)
        if elevation_deg <= 0.0:
            return np.zeros(len(ids), dtype=np.float32)
        self.ensure(ids)

        opaque, low, high, weight = self._bin_lerp(LAYER_OPAQUE, ids, azimuth_deg)
        lit = (opaque < elevation_deg).astype(np.float32)

        canopy, _, _, _ = self._bin_lerp(LAYER_CANOPY, ids, azimuth_deg)
        under_canopy = canopy >= elevation_deg
        tau = (
            self.canopy_tau[ids, low].astype(np.float32) * (1.0 - weight)
            + self.canopy_tau[ids, high].astype(np.float32) * weight
        ) / 255.0
        transmittance = np.where(under_canopy, tau, 1.0).astype(np.float32)
        return (lit * transmittance).astype(np.float32)

    def svf(self, sample_ids: np.ndarray) -> np.ndarray:
        """svf = 1 - mean(sin^2 beta) over the opaque bins.

        Free, because we already have beta in every direction. We need svf for
        the longwave terms in the thermal model, so this is a real saving.
        """
        ids = np.asarray(sample_ids, dtype=np.int64)
        self.ensure(ids)
        beta = np.radians(self.store[LAYER_OPAQUE, ids].astype(np.float32))
        return (1.0 - np.mean(np.sin(beta) ** 2, axis=1)).astype(np.float32)

    def invalidate_within(self, x: float, y: float, radius_m: float) -> int:
        """Planting trees invalidates only what it can possibly affect."""
        if not len(self.samples_xy):
            return 0
        if self._sample_tree is None:
            from scipy.spatial import cKDTree

            self._sample_tree = cKDTree(self.samples_xy)
        ids = np.asarray(
            self._sample_tree.query_ball_point([x, y], radius_m),
            dtype=np.int64,
        )
        if not len(ids):
            return 0
        affected = ids[self.warm[ids]]
        self.warm[affected] = False
        return int(len(affected))

    def warm_all(self, progress: bool = True) -> None:
        """`make warm`. Identical code path to a lazy warm — this is an
        optimisation flag, not a separate system."""
        ids = np.arange(len(self.samples_xy), dtype=np.int64)
        if not progress:
            self.ensure(ids)
            return
        from tqdm import tqdm

        chunk = 2000
        for start in tqdm(range(0, len(ids), chunk), desc="warming", unit="chunk"):
            self.ensure(ids[start : start + chunk])
