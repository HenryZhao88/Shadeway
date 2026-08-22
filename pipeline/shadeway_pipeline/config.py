"""One city profile. Change SCOPES here to cut Brooklyn — that's the whole cut."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SOURCE_CRS = "EPSG:4326"  # what the Socrata API actually serves (see DATA-FINDINGS #1)
SHAPEFILE_CRS = "EPSG:2263"  # what the planimetric SHAPEFILE downloads use, if you ever need them
TARGET_CRS = "EPSG:32118"  # NAD83 / New York Long Island (METRES)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.environ.get("SHADEWAY_CACHE", REPO_ROOT / "data" / "cache"))
OUT_DIR = Path(os.environ.get("SHADEWAY_OUT", REPO_ROOT / "data" / "nyc"))

SOCRATA_DOMAIN = "data.cityofnewyork.us"

FEET_TO_M = 0.3048  # CSCL/building attributes are imperial even when geometry is metric


@dataclass(frozen=True)
class Scope:
    name: str
    boroughs: list[str]  # CSCL borough codes: 1 Manhattan, 3 Brooklyn
    bbox_wgs84: tuple[float, float, float, float]  # west, south, east, north


SCOPES: dict[str, Scope] = {
    # A handful of blocks. Use this while developing — everything runs in seconds.
    "midtown": Scope("midtown", ["1"], (-74.0000, 40.7450, -73.9700, 40.7650)),
    # The demo scope, and the fallback if anything is too slow.
    "manhattan": Scope("manhattan", ["1"], (-74.0250, 40.6980, -73.9060, 40.8830)),
    # The full spec scope.
    "manhattan_brooklyn": Scope(
        "manhattan_brooklyn", ["1", "3"], (-74.0500, 40.5700, -73.8330, 40.8830)
    ),
}

DEFAULT_SCOPE = "manhattan"

# Geometry knobs. Changing these changes the output; they are not style choices.
SIDEWALK_OFFSET_M = 6.0  # fallback only: used for the 7.2% of segments with no
                         # streetwidth. Everything else uses offset_for() — see
                         # DATA-FINDINGS #7.
SIDEWALK_HALF_WIDTH_M = 2.0  # curb to sidewalk centreline
MAX_STREETWIDTH_FT = 120.0  # above this it is a plaza, not a street
MIN_EDGE_LENGTH_M = 3.0  # drop degenerate slivers
CROSSING_MAX_SPAN_M = 40.0  # refuse to synthesise absurd crossings


def offset_for(streetwidth_ft: float | None) -> float:
    """Sidewalk offset from the segment's own street width (DATA-FINDINGS #7).

    A 70 ft avenue gets a 12.7 m offset; a 30 ft side street gets 6.6 m. On a
    wide avenue the two sidewalks are ~25 m apart — at 3 pm that is the
    difference between full sun and full shade, so per-street widths are not a
    nicety here.
    """
    if not streetwidth_ft or streetwidth_ft <= 0:
        return SIDEWALK_OFFSET_M
    half_m = min(streetwidth_ft, MAX_STREETWIDTH_FT) * FEET_TO_M / 2.0
    return half_m + SIDEWALK_HALF_WIDTH_M
