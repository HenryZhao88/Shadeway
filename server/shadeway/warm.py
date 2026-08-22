"""Pre-warm the horizon cache. CALLED FROM THE BUILD, not from the server.

It walks every sample point through the identical code path a lazy query would.
`scripts/build_artifact.py` invokes this during the Vercel build and saves the
result; the deployed server then mmaps that file and never warms anything.

Nothing in the architecture depends on WHEN it runs — that is exactly why moving
it to build time was a free win. See 05-deploy.md.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from shadeway.horizon import HorizonCache
from shadeway.router.graph import Graph
from shadeway.scene import Scene


def main() -> None:
    parser = argparse.ArgumentParser(description="pre-warm the horizon cache")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="optional .npz to save the warmed cache to")
    args = parser.parse_args()

    started = time.time()
    graph = Graph.load(args.data)
    scene = Scene.load(args.data)
    cache = HorizonCache(scene, graph.sample_xy)
    print(f"{graph.n_samples} samples, {cache.nbytes / 1e6:.0f} MB of uint8")
    cache.warm_all()
    elapsed = time.time() - started
    print(
        f"warmed in {elapsed:.1f}s "
        f"({elapsed / max(1, graph.n_samples) * 1e3:.2f} ms/sample)"
    )

    if args.out:
        import numpy as np

        np.savez_compressed(args.out, store=cache.store, tau=cache.canopy_tau)
        print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
