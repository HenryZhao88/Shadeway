# Model notes

## Tmrt model constants

| Constant | Value | Source | Confidence |
|---|---|---|---|
| Stefan–Boltzmann σ | 5.670374419e-8 W m⁻² K⁻⁴ | CODATA 2018 | exact |
| Human shortwave absorptivity a_k | 0.70 | ISO 7726 via UMEP SOLWEIG (`absK=0.7`) | high |
| Human longwave emissivity ε_p | 0.97 | ISO 7726 via UMEP SOLWEIG (`absL=0.97`) | high |
| Angular weights (up/down/4 sides) | 0.06 / 0.06 / 0.22×4 (sum 1.00) | UMEP SOLWEIG standing defaults, ISO 7726 / VDI 3787 | high |
| Cylinder direct-beam factor Fcyl | 0.28 | UMEP SOLWEIG standing default | high |
| Sky emissivity formula | Prata 1996: ε=1−(1+ξ)exp(−(1.2+3ξ)^½), ξ=46.5·e₀/T₀ | Prata 1996 QJRMS 122:1103 | high |
| Cloud correction | linear blend clear→1 by cloud fraction | documented approximation (SOLWEIG needs an observed cloud-index series) | medium |
| Sunlit surface temperature bump | +18 °C at full insolation | inside design-doc range +10..+20 | approximate |
| Shaded surface temperature bump | +2 °C scaled by Ig/900 | inside design-doc range +0..+3 | approximate |
| Wall albedo (default) | 0.20 | UMEP SOLWEIG `albedo_b` example default | medium |

Model shape: UMEP SOLWEIG cylinder formulation — `Sstr = absK·(K_cyl·Fcyl +
Σfaces) + absL·(ΣL faces)`, `Tmrt = (Sstr/(absL·σ))^¼ − 273.15`. Each face's
view splits between sky (cold, ε_sky) and obstructions (warm, ≈ surface
temperature); in a canyon the upward face sees overhanging walls, not sky.
Surface-temperature bumps are the least-sourced constants; they shift Tmrt by
~1–2 °C between their plausible bounds and are flagged as approximate.

## Performance (the Day-1 Spike)

Measured 2026-08-22, bicriteria label-setting search (`shadeway.router.bicriteria`)
with a constant cost function on the **real Manhattan graph** (138,439 edges,
33,851 nodes, `data/nyc`):

| route | p50 | max |
|---|---|---|
| Bryant Park → Grand Central | 495 ms | 530 ms |
| Midtown crosstown | 506 ms | 536 ms |
| Battery → Harlem (full island) | 532 ms | 539 ms |

**OVERALL p50 ≈ 500 ms, worst ≈ 540 ms → under the 1 s bar. Vercel Hobby plan CONFIRMED.**
No λ-sweep fallback needed; no Oracle migration.

## Tree transmissivity (τ) — sourced values

Anchors (all read 2026-08-22):
- **Konarska et al. 2014**, Theor. Appl. Climatol. 117:363–376, DOI 10.1007/s00704-013-1000-3 —
  foliated urban crowns transmit **1–5 % of the direct beam**, 8–15 % of total shortwave
  (Gothenburg, five species).
- **Arboriculture & Urban Forestry 16(6):158** — pyranometer-based summer TOTAL
  transmissivities span **0.08 (horsechestnut) to 0.38 (thornless honeylocust)**.
- **Szeged campaign** (Hungarian Geographical Bulletin 65(2), 2016 / ICUC9 ucp10) —
  midsummer medians: *Tilia cordata* ≈ 0.08, *Styphnolobium japonicum* ≈ 0.10–0.15,
  *Celtis occidentalis* ≈ 0.04.

Our τ is a beam-transmission factor over whole crowns, so species ordering follows
AUF/Szeged totals and every value stays inside the cited 0.04–0.38 band.
`validate.py` reports **23 % of trees use genus/global defaults** (under the 50 %
soft threshold). Per-species τ is an improvement over SOLWEIG's single vegetation
default.

Known gap: none of Konarska's five measured species are in NYC's top eight; the
honeylocust (0.38) and horsechestnut (0.08) anchors bracket the table but
NYC-specific measurements would tighten it.

## Ground albedo

From the NYC 2010 3 ft LiDAR land-cover raster (`9auy-76zt`, ERDAS HFA, opens as
EPSG:2263 — verified live). Sourced values (read 2026-08-22):

| class | surface | albedo | source |
|---|---|---|---|
| 1 | tree canopy | 0.18 | Oke DecTr via SUEWS Typical Values |
| 2 | grass/shrub | 0.21 | Oke grass; NREL range 0.15–0.26 |
| 3 | bare soil | 0.20 | Oke bare soil 0.19–0.21 |
| 4 | water | 0.07 | Oke water 0.10 (low end, fresh water) |
| 5 | building roof | 0.15 | Oke buildings via SUEWS |
| 6 | asphalt road | 0.12 | Oke paved; NREL asphalt 0.09–0.18 |
| 7 | concrete sidewalk | 0.25 | NREL concrete 0.20–0.40 (low-mid) |

## Canopy cross-check (Task 8)

`validate_canopy.compare_canopy` on midtown against the LiDAR canopy raster,
after calibration:

- **recall 0.38 / precision 0.51** with `crown_b = 0.70`
- as-built `crown_b = 0.60` was recall 0.28 — systematically undersized crowns
- calibration note: the street-tree census misses park interiors (hurting
  recall) and crowns overhang buildings (hurting precision), so neither metric
  approaches 1.0 honestly; both now sit in the healthy band
- allometry exponents recorded in `scene/species.py` with this citation

## Graph scope decisions

- Walkable CSCL rw_types {1, 6, 7, 10}.
- Sidewalk offsets per segment from CSCL `streetwidth` (feet→metres, clamped at
  120 ft); fallback 6 m for the ~7 % without width.
- Crossings synthesised from KD-tree endpoint pairs ≤ 40 m across different
  streets; spans ≤ 15 m kept unconditionally, longer links added only when they
  merge components (~116 k crossings).
- **Island exclusions**: Roosevelt Island, Randall's/Ward's Islands, Governors
  Island, Marble Hill (Bronx-attached) — geographically separate in our model;
  see `ISLAND_EXCLUSIONS_WGS84` in config.py.
- A street emits both sidewalk sides or neither (half-streets break per-side
  guidance).

## Validation snapshot (Manhattan, 2026-08-22)

- connectivity 0.970 · both-sides 0 missing · samples tile exactly (520,741)
- crossings ≤ 40 m ✓ · buildings n=44,793 (p99 124 m, max 435 m)
- horizon cache: 520,741 samples × 144 B ≈ **75 MB** uint8
