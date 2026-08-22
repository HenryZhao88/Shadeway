"""The lazy horizon cache. This is why runtime ray casting is fast enough.

Layout: store[layer][sample_id][bin], uint8, 144 bytes per sample point.
  layer 0 = opaque obstruction angle (buildings), degrees
  layer 1 = highest elevation at which canopy still intercepts, degrees
  bin b   = azimuth b * 5 degrees, 0 = north

Warming an entry costs a few ms (144 rays). Reading one is an array index.
"""

from __future__ import annotations

import numpy as np

from shadeway import occluder
from shadeway.scene import Scene

AZIMUTH_BINS = 72
BIN_WIDTH_DEG = 360.0 / AZIMUTH_BINS
LAYER_OPAQUE = 0
LAYER_CANOPY = 1


class HorizonCache:
    def __init__(self, scene: Scene, samples_xy: np.ndarray) -> None:
        self.scene = scene
        self.samples_xy = np.asarray(samples_xy, dtype=np.float64)
        n = len(self.samples_xy)
        self.store = np.zeros((2, n, AZIMUTH_BINS), dtype=np.uint8)
        self.warm = np.zeros(n, dtype=bool)
        # cached tau product per (sample, bin) so f_sun doesn't re-walk crowns
        self.canopy_tau = np.ones((n, AZIMUTH_BINS), dtype=np.float32)

    @property
    def nbytes(self) -> int:
        return int(self.store.nbytes)

    def load_precomputed(self, path) -> bool:
        """Load a build-time warmed cache (`shadeway.warm --out`). Returns True
        on success. Store is mmapped read-only; tau and warm flags come along.
        Missing or shape-mismatched files are ignored, not fatal."""
        import numpy as np

        try:
            data = np.load(path, mmap_mode="r")
            store = data["store"]
            tau = data["tau"]
        except Exception:
            return False
        if store.shape != self.store.shape or tau.shape != self.canopy_tau.shape:
            return False
        # copy into writable RAM: Vercel bundles are read-only but small enough
        # (75 MB for Manhattan); local runs can mmap later if memory matters
        self.store[:] = store
        self.canopy_tau[:] = tau
        self.warm[:] = True
        return True

    def ensure(self, sample_ids: np.ndarray) -> None:
        ids = np.asarray(sample_ids, dtype=np.int64)
        cold = ids[~self.warm[ids]]
        for sample_id in np.unique(cold):
            x, y = self.samples_xy[sample_id]
            self.store[LAYER_OPAQUE, sample_id] = occluder.building_horizon_profile(
                self.scene, float(x), float(y), AZIMUTH_BINS
            )
            self.store[LAYER_CANOPY, sample_id] = occluder.canopy_horizon_profile(
                self.scene, float(x), float(y), AZIMUTH_BINS
            )
            self.canopy_tau[sample_id] = self._tau_profile(float(x), float(y))
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
            self.canopy_tau[ids, low] * (1.0 - weight)
            + self.canopy_tau[ids, high] * weight
        )
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
        distance = np.hypot(
            self.samples_xy[:, 0] - x, self.samples_xy[:, 1] - y
        )
        affected = (distance <= radius_m) & self.warm
        self.warm[affected] = False
        return int(affected.sum())

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
