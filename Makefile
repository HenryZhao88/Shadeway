PY := .venv/bin/python
PIP := uv pip install --python .venv/bin/python
DATA ?= data
SCOPE ?= manhattan
# Where a build lands. Override it to keep scopes side by side rather than
# overwriting one with the other — a rebuild renumbers sample ids, so it also
# throws away the matching horizon.npz.
#   make data warm serve SCOPE=manhattan_brooklyn OUT=data/nyc_mb
OUT ?= $(DATA)/nyc

.PHONY: venv install test lint fixtures types validate data amenities warm serve stub dev clean

venv:
	uv venv --python 3.11 --allow-existing .venv

install: venv
	$(PIP) -U pip
	$(PIP) -e contracts[dev] -e pipeline[dev] -e server[dev]
	npm install

test:
	$(PY) -m shadeway_contracts.export_ts --out web/src/api/types.ts --check
	$(PY) -m pytest contracts/tests server/tests pipeline/tests -q --import-mode=importlib
	npm --workspace web run test -- --run

lint:
	.venv/bin/ruff check contracts pipeline server
	npm --workspace web run lint

types:
	$(PY) -m shadeway_contracts.export_ts --out web/src/api/types.ts

fixtures:
	$(PY) -m shadeway_contracts.fixtures --out $(DATA)/fixtures

data:
	$(PY) -m shadeway_pipeline.emit --out $(OUT) --scope $(SCOPE)

amenities:
	# Rebuilds amenities.parquet alone, against the graph already in $(OUT).
	# A full `make data` renumbers sample ids and invalidates horizon.npz; this
	# does not, because nothing else is keyed to an amenity id.
	$(PY) -m shadeway_pipeline.emit --out $(OUT) --scope $(SCOPE) --only amenities

validate:
	$(PY) -m shadeway_pipeline.validate --data $(OUT)

warm:
	$(PY) -m shadeway.warm --data $(OUT) --out $(OUT)/horizon.npz

serve:
	.venv/bin/uvicorn shadeway.api:app --reload --port 8000

stub:
	.venv/bin/uvicorn shadeway.stub_api:app --reload --port 8000

dev:
	npm --workspace web run dev

clean:
	rm -rf .venv web/node_modules node_modules $(DATA)/fixtures
