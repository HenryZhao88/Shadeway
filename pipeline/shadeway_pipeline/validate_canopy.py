"""Rasterise our modelled crowns and compare against the LiDAR canopy raster.

recall    = of the pixels the raster calls canopy, what fraction did we cover?
            low recall  -> our crowns are too small, or we're missing trees
            (the census is street trees only; park interiors will always miss)
precision = of the pixels we call crown, what fraction does the raster agree with?
            low precision -> our crowns are too big

Both numbers matter and neither should be near 1.0 in the real city: the census
has no park trees (hurts recall) and crowns overhang buildings we can't see
under (hurts precision). What you're looking for is a *systematic* miss —
recall under ~0.35 or precision under ~0.35 means the allometry is wrong, not
that the data is imperfect.
"""

from __future__ import annotations


def compare_canopy(crowns, canopy) -> dict:
    if canopy is None:
        return {
            "status": "skipped",
            "reason": "canopy raster not available in the cache",
            "recall": None,
            "precision": None,
            "modelled_area_m2": None,
            "raster_area_m2": None,
        }
    import numpy as np

    mask, transform = canopy
    height, width = mask.shape
    inverse = ~transform

    modelled = np.zeros_like(mask, dtype=bool)
    yy, xx = np.mgrid[0:height, 0:width]
    for crown in crowns.itertuples():
        col, row = inverse * (crown.x_m, crown.y_m)
        radius_px = crown.crown_radius_m / abs(transform.a)
        if radius_px <= 0:
            continue
        lo_r = int(max(0, row - radius_px - 1))
        hi_r = int(min(height, row + radius_px + 2))
        lo_c = int(max(0, col - radius_px - 1))
        hi_c = int(min(width, col + radius_px + 2))
        if lo_r >= hi_r or lo_c >= hi_c:
            continue
        sub_r = yy[lo_r:hi_r, lo_c:hi_c] + 0.5
        sub_c = xx[lo_r:hi_r, lo_c:hi_c] + 0.5
        inside = (sub_c - col) ** 2 + (sub_r - row) ** 2 <= radius_px**2
        modelled[lo_r:hi_r, lo_c:hi_c] |= inside

    pixel_area = abs(transform.a * transform.e)
    intersection = int((modelled & mask).sum())
    return {
        "status": "ok",
        "recall": intersection / max(1, int(mask.sum())),
        "precision": intersection / max(1, int(modelled.sum())),
        "modelled_area_m2": float(modelled.sum() * pixel_area),
        "raster_area_m2": float(mask.sum() * pixel_area),
    }
