"""Fail a production image build unless it contains a real warmed city."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from shadeway.horizon import source_fingerprint

REQUIRED_PARQUET = (
    "amenities.parquet",
    "buildings.parquet",
    "edges.parquet",
    "nodes.parquet",
    "samples.parquet",
    "trees.parquet",
)
MIN_PRODUCTION_EDGES = 10_000
AZIMUTH_BINS = 72


def verify(root: Path) -> tuple[int, int]:
    missing = [name for name in (*REQUIRED_PARQUET, "horizon.npz") if not (root / name).is_file()]
    if missing:
        raise ValueError(f"city artifact is missing: {', '.join(missing)}")

    edge_count = pq.read_metadata(root / "edges.parquet").num_rows
    sample_count = pq.read_metadata(root / "samples.parquet").num_rows
    if edge_count < MIN_PRODUCTION_EDGES:
        raise ValueError(
            f"refusing fixture-sized city with {edge_count} edges; "
            f"production requires at least {MIN_PRODUCTION_EDGES}"
        )

    with np.load(root / "horizon.npz", allow_pickle=False) as cache:
        if not {"store", "tau", "fingerprint"}.issubset(cache.files):
            raise ValueError("horizon cache must use the fingerprinted v2 format")
        fingerprint = cache["fingerprint"]
        if fingerprint.shape != () or str(fingerprint.item()) != source_fingerprint(root):
            raise ValueError("horizon cache fingerprint does not match the city source files")
        store = cache["store"]
        tau = cache["tau"]
        if store.dtype != np.uint8 or tau.dtype != np.uint8:
            raise ValueError("horizon cache must use compact uint8 arrays")
        if store.shape != (2, sample_count, AZIMUTH_BINS):
            raise ValueError(f"horizon store has the wrong shape: {store.shape}")
        if tau.shape != (sample_count, AZIMUTH_BINS):
            raise ValueError(f"horizon tau has the wrong shape: {tau.shape}")

    return edge_count, sample_count


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_city.py PATH")
    root = Path(sys.argv[1])
    try:
        edge_count, sample_count = verify(root)
    except ValueError as exc:
        raise SystemExit(f"invalid production city: {exc}") from exc
    print(
        f"validated production city: {edge_count} edges, "
        f"{sample_count} samples, compact warmed cache"
    )


if __name__ == "__main__":
    main()
