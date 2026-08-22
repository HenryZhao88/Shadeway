# Model notes

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
EPSG:2263 — verified live). Class→albedo values in
`pipeline/shadeway_pipeline/sources/landcover.py` are still marked PLACEHOLDER:
they need literature citations (Oke Table 1.1 / UMEP defaults) before the demo.

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
