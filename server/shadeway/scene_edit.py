"""Plant trees into the live scene and invalidate exactly what they can shade.

This is Task 13 from the plan: the planting post-pass that turns the demo line
"plant 40 trees on this corridor and re-run" into a real feature. The URL
surface stays frozen in api.py; all scene mutation lives here.

The constants below MIRROR `shadeway_pipeline/scene/species.py` (the pipeline
owns the full sourced table; the server may not import it — see the layering
rules in docs/contracts.md). Keep the two in sync when calibrating.
"""

from __future__ import annotations

# Allometry (pipeline DEFAULT_ALLOMETRY):
#   crown_radius_m = 0.55 * dbh_cm ** 0.70
#   height_m       = 1.35 * dbh_cm ** 0.62
# source: PSW-GTR-253 dimension ranges; exponents LiDAR-cross-check-calibrated
CROWN_A, CROWN_B, HEIGHT_A, HEIGHT_B = 0.55, 0.70, 1.35, 0.62
CROWN_BASE_FRACTION = 0.35
CROWN_BASE_MIN_M = 2.0

# Genus transmissivity, condensed from the sourced table in
# pipeline/shadeway_pipeline/scene/species.py (which carries the citations).
GENUS_TAU: dict[str, float] = {
    "gleditsia": 0.38,
    "celtis": 0.04,
    "tilia": 0.08,
    "platanus": 0.10,
    "pyrus": 0.10,
    "quercus": 0.12,
    "acer": 0.10,
    "styphnolobium": 0.13,
    "sophora": 0.13,
    "zelkova": 0.15,
    "ulmus": 0.15,
    "ginkgo": 0.20,
    "prunus": 0.25,
    "betula": 0.25,
    "fraxinus": 0.25,
}
GLOBAL_TAU = 0.18  # midpoint of the cited 0.08-0.38 band


def genus_of(species: str) -> str:
    return (species or "").strip().split(" ")[0].lower()


def tau_for(species: str) -> float:
    return GENUS_TAU.get(genus_of(species), GLOBAL_TAU)


def crown_geometry(species: str, dbh_cm: float) -> tuple[float, float, float, float]:
    """(crown_radius_m, crown_base_m, crown_top_m, tau) for one planted tree."""
    dbh = max(float(dbh_cm), 1.0)
    top = max(3.0, HEIGHT_A * dbh**HEIGHT_B)
    base = max(CROWN_BASE_MIN_M, top * CROWN_BASE_FRACTION)
    radius = max(0.8, CROWN_A * dbh**CROWN_B)
    return radius, base, max(top, base + 1.0), tau_for(species)
