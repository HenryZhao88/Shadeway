# shadeway

Pedestrian routing for New York that tells you what the walk will *feel like*, in
degrees, and models the sun moving while you walk.

    make install     # venv + python packages + npm
    make fixtures    # synthetic city, no downloads needed
    make stub        # fixture-backed api on :8000
    make dev         # web client on :5173

Real data:

    make data        # download + build graph.parquet / scene.parquet (slow, once)
    make warm        # precompute horizon cache — takes ~1 h for Manhattan
    make serve       # the real api on :8000

Serving without a warm cache works — it fills lazily and `/api/health` reports
`warm_fraction` — but the first route through each block is slow, so warm it
ahead of a demo. Measured costs are in `docs/model.md`.

Scope is Manhattan by default. Both boroughs, kept side by side rather than
overwriting the Manhattan build:

    make data validate SCOPE=manhattan_brooklyn OUT=data/nyc_mb
    make warm  SCOPE=manhattan_brooklyn OUT=data/nyc_mb   # ~4.3 h — run it overnight
    make serve SCOPE=manhattan_brooklyn OUT=data/nyc_mb

Note that Manhattan and Brooklyn are two separate walking networks — every East
River crossing is `rw_type` 3, which the pipeline excludes along with the
vehicle bridges, so no route runs between them. `make validate` checks
connectivity per borough for exactly this reason.

Rebuilding only the amenities table, against a graph you already have — this is
the one you want, because a full `make data` renumbers sample ids and throws away
a warm `horizon.npz`:

    make amenities

Ship it — one container serving the API and the client, no keys, ~593 MB
resident. Free-host options and the numbers behind them: `docs/deploy.md`.

    make docker
    make docker-run                        # http://localhost:8000
    ./deploy/push-to-hf.sh <user>/<space>  # Hugging Face Spaces (x86, 16 GB, free)

Checks:

    make test        # contracts + server + pipeline + web, and the generated types
    make lint        # ruff + eslint

## What is where

| | |
|---|---|
| `pipeline/` | offline, never ships. NYC open data → `graph.parquet`, `scene.parquet`. |
| `server/` | FastAPI. Ray casting, horizon cache, thermal model, bicriteria router. |
| `web/` | React + MapLibre + deck.gl. Draws its own shadows, so the scrubber never waits. |
| `contracts/` | the three frozen shapes all of the above agree on. |

Design notes: `shadeway_design.md`. Frozen interfaces: `docs/contracts.md`.
The physics, with citations and its stated limits: `docs/model.md`.

<details>
<summary><strong>Status — what landed this round, and what is still open</strong></summary>

### Landed

**It is deployed and reachable.** Oracle Cloud Always Free,
`VM.Standard.A1.Flex`, 4 OCPU / 24 GB, Ubuntu 22.04 aarch64, running as a
systemd unit with `Restart=always`. One container serves the API and the
client it renders. 509 MB resident of 23 GB. Getting there needed a VCN,
internet gateway, route, security list and public subnet — all built and all
inside the free allowance.

`VM.Standard.A1.Flex` capacity is the real obstacle, not configuration: AD-1
refused 4/24, 2/12 and 1/6 in turn before a retry sweep caught a full 4/24 in
AD-3. Expect to wait, and expect the wait to be unrelated to anything you did.

**Two client features that were computed and never shown.** The route's
heat-vs-time curve — the store had been fetching that series on every route
and discarding it — and the exposure numbers on the compare card (sun share,
canopy share, sky view, p90 block).

**Four bugs, each of which only appears outside the happy path:**

| | |
|---|---|
| `/timeseries` froze the weather | one cost model for the whole window moved the sun but not the air temperature, flattening the curve. One model per hour now: 26.5 °C → 20.6 °C where it used to hold 26.1 °C. |
| `pyproj` and `scipy` undeclared | imported at runtime, absent from `server/pyproject.toml`. Worked only because a dev machine also installs the pipeline. A container crashed on the first request. |
| every Brooklyn node labelled Manhattan | `nodes["borough"]` was hardcoded `"1"`, and buildings were fetched for one borough only — half the occluders, silently. |
| the map never retried a failed first load | it remembered the bbox it failed on, so a slow-starting server left the city empty until someone panned. |

**Three validator checks that were lying** — one failing a correct
manhattan+brooklyn build, two reporting decisions as unfinished work. See
`docs/model.md`.

### Still open

**Brooklyn is built but not warmed or deployed.** `data/nyc_mb` exists,
validates, and carries 1,867,021 sample points; it has no `horizon.npz`.
Warming it is **~4.3 hours** measured (121 sample points/second across 9
workers) — the design doc's "about 3 minutes" is out by roughly 85×. The
deployed container ships Manhattan.

**Route latency on the server is ~1,500 ms**, against ~400 ms on an Apple
Silicon laptop. The bicriteria search is single-threaded Python and Ampere
Altra cores are weak per-core. Usable, not instant. The map still *feels*
instant because the shadows are computed in the browser, which is the point
of that design — but the number is the number.

**The deployment is plain HTTP on an IP address.** Fine for a demo, not for
sharing widely. Wants a domain and Caddy or certbot.

**`tau` is stored as `float32`** — 150 MB of the 225 MB Manhattan cache, twice
the size of the `uint8` horizon store it accompanies. Quantising to `uint8`
loses nothing real (transmissivity is cited to two decimal places at best,
across a literature band of 0.08–0.38) and would bring the container to
~480 MB, which is what makes a 512 MB free tier viable. It changes the
on-disk cache format and invalidates every warmed `horizon.npz`, so it is a
deliberate change rather than a default.

**The Hugging Face path is built but never exercised end to end.**
`deploy/push-to-hf.sh` and the Space card are written and the amd64 image is
verified locally; nobody has pushed to an actual Space.

**Smaller, in rough order of worth:**

- `Instruction.type == "continue"` is in the contract and never emitted.
- Rest stops are spliced into the instruction list by ordering, not by exact
  leg position — instructions carry no leg index.
- `sunlit_until` answers to a 5-minute step. It is a headline, not an
  ephemeris.
- Cool waypoints only fire above the 26 °C heat-stress line, so on a mild day
  the feature is invisible. Correct, but it means the demo needs a hot day.
- `docs/superpowers/plans/.../05-deploy.md` designs a Vercel deployment that
  is now superseded; its budget table under-counts the cache by ~3×. It is
  left in place as a record, with the arithmetic corrected in
  `docs/deploy.md`.

**Not a gap, so nobody re-opens it:** `edges.width_m` is null on every edge
and always will be. Both NYC sidewalk datasets are Socrata "map" assets that
serve null geometry through the API. Offsets come from CSCL `streetwidth`
instead, for 98% of Manhattan streets.

</details>
