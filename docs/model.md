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

## Instruction evidence — what we can and cannot prove

`InstructionWhy` carries three claims under a turn card. Each is computed, and
each has a stated limit.

**`delta_c`** — the felt-temperature difference between the sidewalk being left
and the one being joined, both evaluated at the moment of the crossing. Straight
from the routed legs; no approximation beyond the model itself.

**`sunlit_until_iso`** — for the side being left, the first future moment its
mean `f_sun` drops below 0.5. Computed by stepping the horizon cache forward in
5-minute increments over a 6-hour window (`server/shadeway/evidence.py`). It
answers to the step, not to the second, and it returns nothing at all when the
side being left is already shaded — a "shade ends at 4pm" reading of a shaded
block would be exactly backwards.

**`shaded_by`** — the identity of the occluder. Two honest limits:

  * *Buildings have no names.* NYC Building Footprints carries BIN, height and
    construction year; `name` is null for essentially every footprint, and we do
    not load PLUTO. So a blocking building is described by what the data
    actually proves about it — its measured roof height and the street its
    centroid fronts (nearest graph sample) — giving "the 445 m tower on E 43 St",
    never an invented address. The design doc's example line, "shaded by 500
    Fifth", would require an address dataset we do not have.
  * *Canopy is named by genus.* Species comes from the tree census through
    `trees.parquet`, so "honey locusts overhead" is the recorded `spc_latin`
    mapped to a common name. Where `f_sun` sits in the 0.05–0.5 band the card
    says "dappled light, not full shade", because that is what a τ≈0.38 crown
    actually delivers.

## Park entrances are derived, not published

There is no park-entrance dataset on NYC Open Data; searching the Socrata
catalog for "Park Entrance" returns the NYCHA data book and waterfront access
points. `AmenityKind.PARK_ENTRANCE` is therefore derived
(`pipeline/shadeway_pipeline/sources/parks.py`) from Parks Properties
(`enfh-gkve`, 2,064 polygons) against the pedestrian graph: an entrance is a
point on a park boundary within 15 m of a sidewalk edge. Boundary points are
sampled every 15 m, thinned to an 80 m minimum separation, and spread evenly to
a cap of 8 per park so Central Park contributes eight usable gates rather than
six hundred boundary samples. Landscaped medians filed as `typecategory = Mall`
(Broadway Malls, Park Avenue) are excluded: you cannot rest in a median.

Manhattan yields 537 derived entrances across 181 parks.

## Client-side shadows

The shadows on the map are not the routing model's output — they are the same
geometry run in the other direction, in the browser, so the time scrubber costs
no round trip. A prism's shadow on flat ground is its footprint swept along the
anti-solar azimuth by `height / tan(elevation)`, so `web/src/map/shadows.ts`
computes exactly that and draws the convex hull of the footprint and its
translate.

Two approximations, both erring the same way:

  * The convex hull fills any notch in a concave footprint (a courtyard, an
    L-shaped tower), so a drawn shadow is never smaller than the true one.
  * Shadows are cast onto flat ground at z=0; terrain is ignored. Manhattan
    below 96th is flat enough that this is invisible at street scale.

Both overstate shade slightly on screen and neither feeds the routing, which
uses the server's ray caster against the same building heights. Sun position
comes from suncalc (Meeus), which agrees with the server's NOAA implementation
to well inside the 5-degree azimuth bins the horizon cache quantises to — so the
map and the route cannot visibly disagree about which side of a street is lit.

## Cool waypoints — the threshold

The rest-stop post-pass (`server/shadeway/waypoints.py`) accumulates thermal load
as degree-minutes above 26 °C, the UTCI no-stress / moderate-heat-stress boundary
(Bröde et al. 2012, table 1). Time below that boundary contributes nothing, so a
shaded stroll at 24 °C is never told to stop and sit down. A stop is offered once
80 degree-minutes have accumulated — roughly twelve minutes at a felt 33 °C — and
only if water, a cooling site or a park entrance lies inside a 150 s round-trip
detour. The accumulator resets after each stop, capped at two per route.

## The heat-vs-time series carries its own weather

`/api/route/{id}/timeseries` walks one fixed route at N times. A cost model
carries the weather it was constructed with — air temperature, wind, humidity
and the three irradiance terms — and takes only the *sun position* from the
timestamp handed to `traverse`. Building a single model for the whole window
therefore moves the sun across the afternoon while holding the weather frozen at
the departure hour.

Over the fifteen minutes the endpoint originally spanned that was invisible.
Over the six-hour window the client now asks for it is not: a 9 pm walk was
being modelled with 3 pm's air temperature and 183 W/m² of diffuse, which
flattened the curve into a straight line at the departure temperature. The
endpoint now builds one model per hour — hourly is the resolution Open-Meteo
serves and the resolution the weather cache stores, so this costs one UTCI
lookup table per hour and no extra network. Measured on the Times Square →
Grand Central route on 2026-08-24, the corrected series falls 26.5 °C → 20.6 °C
between 15:00 and 21:00 where the frozen version held 26.1 °C throughout.

## What `validate.py` checks, and two things it used to get wrong

**Connectivity is judged per borough.** Manhattan and Brooklyn are not walkable
to each other in this model: every East River crossing is `rw_type` 3, which
`cscl.py` excludes. A correct manhattan+brooklyn build is therefore two large
components, and a scope-wide largest-component check reported 0.673 and failed
it. Per borough the same build is 0.970 (Manhattan) and 0.976 (Brooklyn).

*Consequence worth stating plainly: you cannot route from Manhattan to Brooklyn.*
The Brooklyn Bridge walkway is real and is excluded along with the vehicle
bridges. Including it means admitting selected `rw_type` 3 segments, which is a
deliberate change nobody has made yet.

**Tau sourcing is three tiers, not two.** The old check counted any
`tau_source` containing the substring "default" as unsourced — which swept in
every genus-level entry, because those read *"genus default from Quercus
palustris (AUF …)"*, a real citation for a real measurement on a congener. That
reported 23% of the Manhattan canopy as defaulted when the truly unsourced share
is 6%. Current figures:

| scope | species-level | genus-level | global default |
|---|---|---|---|
| Manhattan | 77% | 18% | 6% |
| Manhattan + Brooklyn | 71% | 21% | 8% |

**Sidewalk widths are not a gap.** `edges.width_m` is null on every edge and
always will be: both NYC sidewalk datasets are Socrata "map" assets that serve
null geometry through the API (DATA-FINDINGS #8), and real geometry means the
planimetric shapefile download, which the earlier investigation judged not worth
it. The check that used to warn about this every build has been replaced by one
that measures what those datasets were actually wanted for — whether the
per-segment offsets came from CSCL `streetwidth` rather than the constant
fallback. They do, for 98% of Manhattan streets and 97% across both boroughs.
On a wide avenue that offset is the difference between the two sidewalks being
13 m and 25 m apart, which is the whole side-of-street claim, so it is the thing
worth watching.

## What `make warm` actually costs

Measured, not estimated — on this machine (9 worker processes, ~800% CPU
sustained), warming `manhattan_brooklyn` runs at **121 sample points per second
across all workers**:

| scope | sample points | resident cache | measured warm |
|---|---|---|---|
| Manhattan | 520,741 | 225 MB | ~1 hour |
| Manhattan + Brooklyn | 1,867,021 | 808 MB | **~4.3 hours** |

The 72,000-sample benchmark that produced the rate: 592.6 s wall, 2,691 s CPU.

Two corrections to `shadeway_design.md` follow from this.

**"about 3 minutes for manhattan plus brooklyn" is out by roughly 85×.** The
architecture claim around it still holds — warming is an optimisation flag, not
a separate system, and the code path is identical to a lazy warm — but the
operational advice ("run it before you present") needs a night, not a coffee.
Serving cold is supported and degrades gracefully: the cache fills lazily per
sample point, `/api/health` reports `warm_fraction`, and the client shows a
banner until it reaches 1.0.

**The resident cache is bigger than the design doc's ~69 MB.** Two reasons: the
graph carries far more sample points than estimated (crossings are 116,045 of
Manhattan's 138,439 edges), and the cache is not only the `uint8` horizon store
— there is also a `float32` canopy-tau array of shape (n, 72), which is twice
the size of the store. Manhattan: 75 MB store + 150 MB tau. Both boroughs:
269 MB + 538 MB.

Storing tau as `uint8` would cut those to 37 MB and 134 MB. Transmissivity is a
number in [0, 1] cited to two decimal places at best, across a literature band
of 0.08–0.38 with genus-level substitutions for a fifth of the canopy, so
quantising to 1/255 ≈ 0.004 is far inside its own uncertainty. Not done here
because it changes the on-disk cache format and invalidates every warmed
`horizon.npz`.
