# Deploying shadeway

One container. It serves the API and the client it renders, so there is one
thing to deploy and no CORS in production.

    make data && make warm      # build the city, warm the cache (see below)
    make docker                 # build the image
    make docker-run             # http://localhost:8000

## Why a server and not a function

`docs/superpowers/plans/2026-08-20-shadeway/05-deploy.md` designs this as a
Vercel Python function. That plan is not what is built here, and the reason is
arithmetic rather than preference.

Its budget table counted `horizon.npy` at 34 MB (Manhattan) / 123 MB (both
boroughs) and put the total at ~134 / ~257 MB, comfortably inside Vercel's
500 MB Python limit. Two things are wrong with that:

- The graph carries far more sample points than estimated — 520,741 for
  Manhattan against a predicted 236,248, because crossings are 116,045 of its
  138,439 edges. The store is **75 MB / 269 MB**, not 34 / 123.
- The cache is not only that two-layer `uint8` store. It also needs a canopy-tau
  array of shape (n, 72). This used to be `float32`, adding 150 MB / 538 MB.

Tau is now `uint8`, so the current allocations are **113 MB for Manhattan and
405 MB for both boroughs**, including warm flags. The previous Manhattan image
measured 593 MB RSS with the 225 MB cache; a fresh-image RSS measurement is
still required before promising a 512 MB host. Both boroughs remain over
Vercel's bundle limit outright. Two further mismatches finish the argument:
Task 5 warms the cache during the Vercel build, against a 45-minute build cap
and a warm that takes hours (below); and stateful planting does not fit a
serverless lifecycle.

A server keeps the design as designed — stateful planting included — and the
measured route latency (~400 ms warm) was always inside the plan's own "< 1 s →
confirmed" gate.

## What it costs to run

Measured, on the built Manhattan scope:

| | |
|---|---|
| image | 935 MB |
| horizon allocation | **113 MB** |
| previous image RSS | **593 MB** (before tau quantisation; remeasure) |
| route, warm cache | ~400 ms |
| route, first call | ~1.3 s (includes the Open-Meteo fetch) |
| startup | a few seconds — loads 43 MB of parquet and the cache |

Both boroughs use a 405 MB horizon allocation; budget total process memory with
headroom until it is measured on the target runtime.

## Free hosts that fit

The old image exceeded 512 MB. The cache change makes that tier plausible, but
do not call it supported until the rebuilt image stays below the cap with
request-time headroom.

| host | free tier | verdict |
|---|---|---|
| **Oracle Cloud Always Free** | 4 ARM cores, 24 GB RAM, always on | Best fit. Runs either scope with room to spare, never sleeps. Wants a card at signup. |
| **Hugging Face Spaces** (Docker, CPU basic) | 2 vCPU, 16 GB RAM | Easiest. No card. Sleeps when idle and wakes on request — fine for a demo, and the startup cost is seconds, not the warm. |
| Google Cloud Run | 360k GiB-s/month | Works, but it scales to zero and every cold start reloads the cache. Set `--memory 1Gi --min-instances 1` and you are outside the free allowance. |
| Render free web service | 512 MB RAM | Needs a fresh-image RSS measurement; the old image OOMed. |
| Fly.io | no standing free allowance since 2024 | Not reliably free. |

Tau is stored as `uint8`: the maximum quantisation error is 0.5/255, below
0.002, while the source values are only supported to roughly two decimal
places. New cache files fingerprint the shade inputs. The loader accepts the
existing legacy Manhattan cache only when its mtime is newer than those inputs,
then quantises it in memory; the next `make warm` writes the new format.

## Warming, and when to do it

`make warm` runs at ~121 sample points per second across 9 workers on a laptop:
roughly **1 hour for Manhattan** and **4.3 hours for both boroughs**. The design
doc's "about 3 minutes" is out by a wide margin — see `docs/model.md`.

So warm on the machine that builds the data, not in a deploy step, and bake the
result into the image. `make docker OUT=...` passes that directory to the
Dockerfile and ships its `horizon.npz` along with the parquet.

Serving cold works and is the honest fallback: the cache fills lazily per sample
point, `/api/health` reports `warm_fraction`, and the client shows a banner
until it reaches 1.0. The first route through a given block pays for its own ray
casting, and every route after that is free.

## Configuration

| variable | default | |
|---|---|---|
| `PORT` | 8000 | Most free hosts inject this. |
| `SHADEWAY_DATA` | `/app/data/nyc` | Which built city to serve. |
| `SHADEWAY_WEB_DIST` | `/app/web/dist` | Unset it to serve the API alone. |
| `SHADEWAY_ENABLE_PLANTING` | `0` | Opt into shared, in-memory scene edits; `make serve` and `make docker-run` enable it locally. |

No API keys anywhere. Weather comes from Open-Meteo, which is keyless and
CORS-open, so the client can fall back to calling it directly if the server dies
mid-demo. Do not put a proxy in front of that.

## One worker, on purpose

Each uvicorn worker holds its own copy of the horizon cache, so two workers cost
226 MB to serve the same read-mostly arrays. The route handler is a sync `def`,
which Starlette already runs in a thread pool, so concurrent requests overlap
wherever numpy releases the GIL. Scale by giving the one process more memory
before adding a second.

## Oracle Cloud, concretely

You must create the account yourself — signup requires a credit card for
identity verification (Always Free resources are not charged against it).

**Shape:** `VM.Standard.A1.Flex`, 4 OCPU / 24 GB, Ubuntu 22.04 (aarch64). Not
`VM.Standard.E2.1.Micro`; its 1 GB leaves much less request-time and OS headroom.

Be warned that A1 is the most contended thing on the free tier. "Out of host
capacity" at instance creation is common and can persist for days in busy
regions; it is not a misconfiguration, and retrying in a different availability
domain is the usual remedy.

1. Create the instance, and under **Show advanced options → Management →
   Cloud-init script** paste `deploy/cloud-init.yaml`.
2. **VCN → Security List → add an ingress rule** for TCP 80 from `0.0.0.0/0`.
3. `./deploy/push-to-instance.sh ubuntu@<public-ip>` — ships the exact image
   that was verified locally (~233 MB compressed) and starts the service.

Two gotchas the cloud-init already handles, both of which make a correct deploy
look broken:

- Oracle's stock images carry an `iptables` INPUT chain that REJECTs everything
  but SSH. Opening the VCN Security List is necessary and **not sufficient** —
  the host firewall needs the rule too.
- The instance must be ARM to match the image. `push-to-instance.sh` checks
  `uname -m` against the image architecture and refuses rather than shipping
  something that will not execute.

## Hugging Face Spaces

The pragmatic answer when Oracle has no free ARM capacity — which is often.
16 GB of RAM, no credit card, no capacity queue, and it builds the Dockerfile
for you.

    ./deploy/push-to-hf.sh <user>/<space-name>

You have to create the account and the Space yourself; the script only pushes.
Create the Space as **Docker → Blank**, then generate a **write**-scoped token at
<https://huggingface.co/settings/tokens> — the push asks for your username and
that token as the password.

**Spaces are x86_64.** Build and test locally with an explicit platform, or you
will verify an image that cannot run there:

    docker build --platform linux/amd64 -t shadeway:amd64 .
    docker run --rm --platform linux/amd64 -p 8400:8000 shadeway:amd64

Measured on the pre-quantisation image: **660 MB** resident, warm cache loaded,
routes correct. Remeasure after rebuilding this version.
(Route latency under local Rosetta emulation is meaningless — it is native x86
on the Space.)

The push ships 44 MB: the Dockerfile, the three Python packages, the web client
and the built city. `horizon.npz` is 17 MB, over the 10 MB threshold, so the
script puts `*.parquet` and `*.npz` under git-lfs. The pipeline, the ~700 MB of
raw NYC downloads and the test suites stay out.

`deploy/huggingface/README.md` is the Space card. Its front matter sets
`sdk: docker` and `app_port: 8000`, which must match the `PORT` the Dockerfile
defaults to — change one and you change the other.

Free Spaces sleep after a period of inactivity and wake on the next request.
Waking costs seconds, not the warm: the cache is baked into the image.
