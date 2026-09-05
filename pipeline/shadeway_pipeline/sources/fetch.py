"""Cached, resumable-ish downloads. Nothing here knows what the data means."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import requests
from tqdm import tqdm

from shadeway_pipeline.config import CACHE_DIR, SOCRATA_DOMAIN

TIMEOUT_S = 120


def cached_download(url: str, filename: str, *, cache_dir: Path | None = None) -> Path:
    """Download `url` to `<cache>/<filename>` unless it is already there.

    Writes to a `.part` file first so an interrupted download never poisons the cache.
    """
    cache_dir = Path(cache_dir or CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / filename
    if target.exists() and target.stat().st_size > 0:
        return target

    partial = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT_S) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            with partial.open("wb") as handle, tqdm(
                total=total, unit="B", unit_scale=True, desc=filename, leave=False
            ) as bar:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    handle.write(chunk)
                    bar.update(len(chunk))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    shutil.move(partial, target)
    return target


def socrata_geojson(
    dataset_id: str, *, where: str | None = None, limit: int = 500_000
) -> Path:
    """Pull a Socrata dataset as GeoJSON. `where` is SoQL, e.g. "boroughcode in ('1','3')"."""
    query = f"$limit={limit}"
    if where:
        query += f"&$where={requests.utils.quote(where)}"
    url = f"https://{SOCRATA_DOMAIN}/resource/{dataset_id}.geojson?{query}"
    # Python's hash() changes between processes, and a limit is part of the
    # response identity too: a one-row probe must not shadow the full export.
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    stem = f"{dataset_id}_{digest}"
    return cached_download(url, f"{stem}.geojson")
