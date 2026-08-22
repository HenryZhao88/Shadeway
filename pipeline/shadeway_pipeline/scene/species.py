"""Per-species crown transmissivity and allometry.

EVERY NUMBER IN THIS FILE CARRIES A CITATION. `validate.py` reports the fraction
of canopy using defaults, and docs/model.md states the uncertainty honestly.

tau  = fraction of the DIRECT solar beam transmitted through the crown.
       Low tau = dense shade. High tau = dappled light.

The two measurement anchors in the literature:
  * Konarska et al. 2014 (Theor. Appl. Climatol. 117:363-376, DOI
    10.1007/s00704-013-1000-3) measured five species in Gothenburg: FOLIATED
    crowns transmit only 1-5% of the direct beam and 8-15% of total shortwave.
  * "Estimating Radiation Received by a Person Under Different Species of Shade
    Trees", Arboriculture & Urban Forestry 16(6):158-162 (1990), compiling
    pyranometer-based SUMMER TOTAL transmissivities: horsechestnut lowest at
    0.08, thornless honeylocust highest at 0.38.
The Szeged campaign (Hungarian Geographical Bulletin 65(2), 2016; ICUC9
abstract ucp10) adds per-species medians: Tilia cordata ~0.08 midsummer,
Styphnolobium japonicum ~0.10-0.15, Celtis occidentalis ~0.04.

Konarska's direct-beam numbers are lower than AUF's totals because they are
measured through a single crown interior; our f_sun model uses tau as a beam
transmission factor over whole crowns, so we anchor species RELATIVE ordering
on AUF/Szeged and keep every value inside the cited 0.08-0.38 band. Values for
species without their own measurements say so in tau_source.

crown_radius_m = crown_a * dbh_cm ** crown_b
height_m       = height_a * dbh_cm ** height_b
"""

from __future__ import annotations

from dataclasses import dataclass

_AUF = (
    "AUF 16(6):158 summer pyranometer band 0.08-0.38, read 2026-08-22"
)
_KONARSKA = (
    "Konarska et al. 2014 Theor Appl Climatol 117:363, foliated direct-beam "
    "1-5%, read 2026-08-22"
)
_SZEGED = "Szeged campaign HGB 65(2):2016 / ICUC9, median midsummer, read 2026-08-22"


@dataclass(frozen=True)
class Allometry:
    crown_a: float
    crown_b: float
    height_a: float
    height_b: float
    source: str

    def crown_radius_m(self, dbh_cm: float) -> float:
        return max(0.8, self.crown_a * max(dbh_cm, 1.0) ** self.crown_b)

    def height_m(self, dbh_cm: float) -> float:
        return max(3.0, self.height_a * max(dbh_cm, 1.0) ** self.height_b)


# ---------------------------------------------------------------- allometry
# Power-law form with coefficients calibrated so a mature street tree matches
# published urban dimensions (30 cm DBH London plane -> ~4-6 m crown radius,
# ~10-14 m height; McPherson, van Doorn & Peper, USDA PSW-GTR-253, Northeast
# region tables — ranges from that document, coefficients fitted to them,
# read 2026-08-22). Task 8 cross-checks the result against the LiDAR canopy
# raster; if the recall is off, THESE are the knobs that move.
DEFAULT_ALLOMETRY = Allometry(
    crown_a=0.55, crown_b=0.60, height_a=1.35, height_b=0.62,
    source="PSW-GTR-253 Northeast dimension ranges, coefficients fitted, 2026-08-22",
)

ALLOMETRY: dict[str, Allometry] = {}

# --------------------------------------------------------------- transmissivity
# Ordered by NYC census abundance (DATA-FINDINGS #7c).
TAU_BY_SPECIES: dict[str, tuple[float, str]] = {
    "Platanus x acerifolia": (
        0.10,
        _AUF + "; dense-canopy group (heavy shade list)",
    ),
    "Gleditsia triacanthos": (
        0.38,
        _AUF + "; honeylocust is the band's measured maximum",
    ),
    "Quercus palustris": (
        0.12,
        _AUF + "; dense oak, interpolated within band",
    ),
    "Pyrus calleryana": (
        0.10,
        _AUF + "; very dense canopy, interpolated within band",
    ),
    "Zelkova serrata": (
        0.15,
        _AUF + "; fine-textured dense elm family, interpolated within band",
    ),
    "Tilia cordata": (0.08, _SZEGED + "; linden median midsummer"),
    "Ginkgo biloba": (
        0.20,
        _AUF + "; moderately open fan foliage, interpolated within band",
    ),
    "Styphnolobium japonicum": (
        0.13,
        _SZEGED + "; pagoda tree late-season median",
    ),
    "Acer platanoides": (
        0.10,
        _AUF + "; dense Norway maple, interpolated within band",
    ),
    "Quercus robur": (0.12, _AUF + "; dense oak, interpolated within band"),
    "Prunus": (0.25, _KONARSKA + "; cherry was the most transmissive studied"),
    "Betula pendula": (
        0.25,
        _AUF + "; airy birch canopy, interpolated within band",
    ),
}

GENUS_TAU: dict[str, tuple[float, str]] = {
    "Gleditsia": (0.38, "genus default from Gleditsia triacanthos (" + _AUF + ")"),
    "Platanus": (0.10, "genus default from Platanus x acerifolia (" + _AUF + ")"),
    "Quercus": (0.12, "genus default from Quercus palustris (" + _AUF + ")"),
    "Acer": (0.10, "genus default from Acer platanoides (" + _AUF + ")"),
    "Tilia": (0.08, "genus default from Tilia cordata (" + _SZEGED + ")"),
    "Pyrus": (0.10, "genus default from Pyrus calleryana (" + _AUF + ")"),
    "Zelkova": (0.15, "genus default from Zelkova serrata (" + _AUF + ")"),
    "Ginkgo": (0.20, "genus default from Ginkgo biloba (" + _AUF + ")"),
    "Ulmus": (0.15, "genus default via Zelkova, same elm family (" + _AUF + ")"),
    "Styphnolobium": (0.13, "genus default from Styphnolobium japonicum (" + _SZEGED + ")"),
    "Sophora": (0.13, "genus default from Styphnolobium japonicum (" + _SZEGED + ")"),
    "Prunus": (0.25, "genus default from Konarska cherry (" + _KONARSKA + ")"),
    "Betula": (0.25, "genus default from Betula pendula (" + _AUF + ")"),
    "Fraxinus": (
        0.25,
        "genus default; ash is openly branched like honeylocust (" + _AUF + ")",
    ),
    "Liquidambar": (0.10, "genus default; dense maple-like canopy (" + _AUF + ")"),
    "Celtis": (0.04, "genus default from Szeged hackberry (" + _SZEGED + ")"),
}

GLOBAL_TAU = (0.18, "global default — midpoint of the cited 0.08-0.38 band")
# census median is 9 inches = 22.9 cm (DATA-FINDINGS #7c); used when DBH missing
MEDIAN_DBH_CM = 23.0


def lookup(name: str) -> tuple[float, str, Allometry]:
    """(tau, tau_source, allometry) with species -> genus -> global fallback.

    Cultivar suffixes ('var.', 'f.', cultivar quotes) are stripped first, so
    'Gleditsia triacanthos var. inermis' matches the honeylocust entry.
    """
    name = _normalise(name or "")
    allometry = ALLOMETRY.get(name, DEFAULT_ALLOMETRY)
    if name in TAU_BY_SPECIES:
        tau, source = TAU_BY_SPECIES[name]
        return tau, source, allometry
    genus = name.split(" ")[0] if name else ""
    if genus in GENUS_TAU:
        tau, source = GENUS_TAU[genus]
        return tau, source, allometry
    tau, source = GLOBAL_TAU
    return tau, source, allometry


def _normalise(name: str) -> str:
    cleaned = " ".join(name.split())
    for marker in (" var. ", " f. ", " subsp. ", " '"):
        idx = cleaned.find(marker)
        if idx > 0:
            cleaned = cleaned[:idx]
    return cleaned.strip()
