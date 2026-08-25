# shadeway, as one container: the API and the client it serves.
#
# Deliberately NOT serverless. The server holds a graph, a scene and a horizon
# cache resident — 225 MB for Manhattan — and answers a route in ~400 ms of
# Python. That is a process, not a function: scale-to-zero would pay the load
# cost on every cold request, and the planting feature mutates scene state that
# a function would forget between calls.
#
# The pipeline is NOT in this image. It downloads gigabytes of NYC open data and
# runs offline on a laptop; what ships is its output. Build the data first:
#
#     make data && make warm
#     docker build -t shadeway .
#     docker run --rm -p 8000:8000 shadeway
#
# See docs/deploy.md for free hosts and their memory limits.

# ---------------------------------------------------------------- web build
FROM node:20-slim AS web

WORKDIR /build
COPY package.json package-lock.json ./
COPY web/package.json ./web/
RUN npm ci --workspace web --include-workspace-root

COPY web ./web
RUN npm --workspace web run build

# ------------------------------------------------------------------ runtime
FROM python:3.11-slim AS runtime

# curl is for the container healthcheck below and nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SHADEWAY_DATA=/app/data/nyc \
    SHADEWAY_WEB_DIST=/app/web/dist

WORKDIR /app

# Dependencies first, so editing source does not re-resolve the whole tree.
COPY contracts/pyproject.toml ./contracts/
COPY server/pyproject.toml ./server/
RUN mkdir -p contracts/shadeway_contracts server/shadeway \
 && touch contracts/shadeway_contracts/__init__.py server/shadeway/__init__.py \
 && pip install ./contracts ./server

COPY contracts ./contracts
COPY server ./server
RUN pip install --no-deps ./contracts ./server

# The built city. `make data` writes the parquet, `make warm` writes
# horizon.npz. Serving without the cache works — it fills lazily and
# /api/health reports warm_fraction — but the first route through each block
# pays for its own ray casting, so bake a warmed one in for anything public.
COPY data/nyc ./data/nyc
COPY --from=web /build/web/dist ./web/dist

# Free hosts inject the port. Default to 8000 for `docker run` on a laptop.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT}/api/health" || exit 1

# One worker on purpose. Each worker would hold its own copy of the horizon
# cache, so two workers cost 450 MB to serve the same read-mostly arrays. The
# route handler is sync, so Starlette already runs it in a thread pool and
# concurrent requests overlap wherever numpy releases the GIL.
CMD ["sh", "-c", "exec uvicorn shadeway.api:app --host 0.0.0.0 --port ${PORT} --workers 1"]
