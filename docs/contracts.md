# Frozen interfaces

Three shapes. Changing any of them requires all three track owners to agree, in one
conversation, and a single commit that updates producer, consumer and tests together.

## 1. `graph.parquet` — `nodes`, `edges`, `samples`
Defined in `contracts/shadeway_contracts/tables.py`. Produced by `pipeline`,
consumed by `server`. Geometry is WKB in EPSG:32118 (metres).

The `edges.sample_start` / `edges.sample_count` pair is load-bearing: the horizon
cache is a dense `uint8[2][n_samples][72]` array indexed directly by `sample_id`,
with no join. Samples for one edge must be contiguous and in walk order from `u`
to `v`.

## 2. `scene.parquet` — `buildings`, `trees`, `amenities`
Same module. Buildings are vertical prisms (`height_m`, `base_m`). Trees are
crowns: circle of `crown_radius_m` between `crown_base_m` and `crown_top_m` with
direct-beam transmissivity `tau`. `tau_source` must cite a real reference or say
`"default"` — never a silent guess.

## 3. The route JSON
Defined in `contracts/shadeway_contracts/api.py`, exported to TypeScript by
`make types`. `web/src/api/types.ts` is generated and `make test` fails if it is
stale.

## Layering
- `contracts` imports nothing from `server` or `pipeline`.
- `server` never imports `pipeline`.
- `pipeline` never imports `server`.
- `server/shadeway/thermal/` is pure: no filesystem, no network, no clock.

**Deviation from `shadeway_design.md`:** the scaffold in the design doc places
`weather.py` under `thermal/`. It does network IO, which breaks the purity rule
that makes the thermal model easy to test. It lives at
`server/shadeway/weather.py` instead. Everything else follows the scaffold.

## Endpoints outside the frozen contract

Two GET endpoints serve map furniture rather than routes, and are typed in the
client by hand rather than generated:

- `GET /api/amenities?bbox=w,s,e,n` — fountains, cooling sites and park
  entrances in view.
- `GET /api/buildings?bbox=w,s,e,n&max_features=N` — occluder footprints with
  heights, tallest first, so the client can cast its own shadows. This is the
  same building set the server's ray caster uses; serving it is what keeps the
  shadows on screen and the shade in the routing from disagreeing.

They are deliberately not in `api.py`: adding them would put viewport plumbing
into the shape three tracks have to agree on. If either ever needs to carry a
number the routing depends on, it moves into the contract first.
