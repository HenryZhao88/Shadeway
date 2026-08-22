"""Pre-warm the horizon cache. CALLED FROM THE BUILD, not from the server.

It walks every sample point through the identical code path a lazy query would.
`scripts/build_artifact.py` invokes this during the Vercel build and saves the
result; the deployed server then mmaps that file and never warms anything.

Nothing in the architecture depends on WHEN it runs — that is exactly why moving
it to build time was a free win. See 05-deploy.md.

Parallelised across CPU cores: each worker rebuilds its own Scene from the data
directory (a couple of seconds, amortised over thousands of samples) and warms
a contiguous slice of samples.
"""

from __future__ import annotations

import argparse
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np

AZIMUTH_BINS = 72


def _warm_slice(args: tuple[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Worker: load the scene fresh and profile one contiguous slice."""
    from shadeway import occluder
    from shadeway.scene import Scene

    data_dir, xy = args
    scene = Scene.load(Path(data_dir))
    n = len(xy)
    opaque = np.zeros((n, AZIMUTH_BINS), dtype=np.uint8)
    canopy = np.zeros((n, AZIMUTH_BINS), dtype=np.uint8)
    tau = np.ones((n, AZIMUTH_BINS), dtype=np.float32)
    for i in range(n):
        x, y = float(xy[i][0]), float(xy[i][1])
        opaque[i] = occluder.building_horizon_profile(scene, x, y)
        canopy[i] = occluder.canopy_horizon_profile(scene, x, y)
        tau[i] = occluder.tau_profile(scene, x, y)
    return opaque, canopy, tau


def warm_parallel(
    data_dir: Path,
    samples_xy: np.ndarray,
    workers: int | None = None,
    chunk_size: int = 8000,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (store uint8[2][n][72], canopy_tau float32[n][72])."""
    workers = workers or max(1, cpu_count() - 1)
    n = len(samples_xy)
    store = np.zeros((2, n, AZIMUTH_BINS), dtype=np.uint8)
    canopy_tau = np.ones((n, AZIMUTH_BINS), dtype=np.float32)

    chunks = [
        (str(data_dir), samples_xy[s : s + chunk_size])
        for s in range(0, n, chunk_size)
    ]
    cursor = 0
    with Pool(workers) as pool:
        for opaque, canopy, tau in pool.imap(_warm_slice, chunks):
            store[0, cursor : cursor + len(opaque)] = opaque
            store[1, cursor : cursor + len(canopy)] = canopy
            canopy_tau[cursor : cursor + len(tau)] = tau
            cursor += len(opaque)
    return store, canopy_tau


def main() -> None:
    parser = argparse.ArgumentParser(description="pre-warm the horizon cache")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="optional .npz to save the warmed cache to")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    from shadeway.router.graph import Graph

    started = time.time()
    graph = Graph.load(args.data)
    nbytes = graph.n_samples * AZIMUTH_BINS * 2
    print(
        f"{graph.n_samples} samples, {nbytes / 1e6:.0f} MB of uint8, "
        f"workers={args.workers or max(1, cpu_count() - 1)}"
    )
    store, canopy_tau = warm_parallel(
        args.data, graph.sample_xy, workers=args.workers
    )
    elapsed = time.time() - started
    print(
        f"warmed in {elapsed:.1f}s "
        f"({elapsed / max(1, graph.n_samples) * 1e3:.2f} ms/sample/core-adjusted)"
    )

    if args.out:
        np.savez_compressed(args.out, store=store, tau=canopy_tau)
        print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
