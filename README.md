# shadeway

Pedestrian routing for New York that tells you what the walk will *feel like*, in
degrees, and models the sun moving while you walk.

    make install     # venv + python packages + npm
    make fixtures    # synthetic city, no downloads needed
    make stub        # fixture-backed api on :8000
    make dev         # web client on :5173

Real data:

    make data        # download + build graph.parquet / scene.parquet (slow, once)
    make warm        # precompute horizon cache — RUN THIS BEFORE ANY DEMO
    make serve       # the real api on :8000

Rebuilding only the amenities table, against a graph you already have — this is
the one you want, because a full `make data` renumbers sample ids and throws away
a warm `horizon.npz`:

    make amenities

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
