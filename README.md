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

Design notes: `shadeway_design.md`. Frozen interfaces: `docs/contracts.md`.
The physics, with citations: `docs/model.md`.
