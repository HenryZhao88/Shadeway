#!/usr/bin/env bash
# Push shadeway to a Hugging Face Docker Space.
#
#     ./deploy/push-to-hf.sh <user>/<space-name>
#
# Assembles a clean tree in a temp directory rather than pushing this repo:
# the Space needs the Dockerfile, the three Python packages, the web client and
# the built city — and nothing else. The pipeline, the raw NYC downloads
# (~700 MB) and the test suites stay out of it.
#
# HF builds the image itself from the Dockerfile, so this ships source, not a
# container. That is also why the Space is x86: build for that platform when
# testing locally (`docker build --platform linux/amd64`).
set -euo pipefail

SPACE="${1:?usage: push-to-hf.sh <user>/<space-name>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${OUT:-data/nyc}"

cd "$REPO_ROOT"

[ -f "$DATA_DIR/edges.parquet" ] || {
  echo "no built city at $DATA_DIR — run 'make data' first" >&2; exit 1; }
[ -f "$DATA_DIR/horizon.npz" ] || {
  echo "no horizon.npz in $DATA_DIR — production builds require a warmed city." >&2
  echo "Run 'make warm OUT=$DATA_DIR' first." >&2
  exit 1
}

command -v git-lfs >/dev/null || { echo "git-lfs required: brew install git-lfs" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
echo "staging in $STAGE"

# Exactly what the Dockerfile copies, plus the Space card.
cp Dockerfile .dockerignore "$STAGE/"
cp package.json package-lock.json "$STAGE/"
cp deploy/huggingface/README.md "$STAGE/README.md"
mkdir -p "$STAGE/deploy"
cp deploy/verify_city.py "$STAGE/deploy/"
for d in contracts server web; do
  rsync -a --exclude node_modules --exclude dist --exclude '__pycache__' \
        --exclude '*.egg-info' --exclude '.pytest_cache' \
        --exclude 'tsconfig.tsbuildinfo' "$d" "$STAGE/"
done
mkdir -p "$STAGE/data"
rsync -a "$DATA_DIR/" "$STAGE/data/nyc/"

cd "$STAGE"
git init -q -b main
git lfs install --local >/dev/null
# The city is binary and large; the source is not.
git lfs track "*.parquet" "*.npz" >/dev/null
git add .gitattributes
git add -A
git -c user.email=deploy@shadeway -c user.name=shadeway commit -qm "shadeway"

echo
echo "about to push $(du -sh . | cut -f1) to https://huggingface.co/spaces/$SPACE"
echo "HF will ask for your username and an access token with WRITE scope"
echo "(create one at https://huggingface.co/settings/tokens)"
echo
git remote add origin "https://huggingface.co/spaces/$SPACE"
git push -f origin main

echo
echo "pushed. HF is now building the image — watch it at:"
echo "  https://huggingface.co/spaces/$SPACE"
echo "first build takes a few minutes; it installs the Python deps and builds the client."
