import numpy as np
import pandas as pd
from affine import Affine

from shadeway_pipeline.validate_canopy import compare_canopy


def _crowns(radius_m: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x_m": [50.0],
            "y_m": [50.0],
            "crown_radius_m": [radius_m],
        }
    )


def _raster_with_a_five_metre_blob() -> tuple[np.ndarray, Affine]:
    """A 100x100 one-metre grid with a disc of radius 5 m at (50, 50)."""
    yy, xx = np.mgrid[0:100, 0:100]
    mask = (xx - 50) ** 2 + (100 - yy - 50) ** 2 <= 25
    transform = Affine.translation(0, 100) * Affine.scale(1, -1)
    return mask, transform


def test_skips_cleanly_when_the_raster_is_missing():
    result = compare_canopy(_crowns(5.0), None)
    assert result["status"] == "skipped"


def test_matching_crowns_score_high_on_both_metrics():
    result = compare_canopy(_crowns(5.0), _raster_with_a_five_metre_blob())
    assert result["status"] == "ok"
    assert result["recall"] > 0.8
    assert result["precision"] > 0.8


def test_crowns_that_are_far_too_small_have_low_recall():
    result = compare_canopy(_crowns(1.0), _raster_with_a_five_metre_blob())
    assert result["recall"] < 0.2


def test_crowns_that_are_far_too_big_have_low_precision():
    result = compare_canopy(_crowns(20.0), _raster_with_a_five_metre_blob())
    assert result["precision"] < 0.2
