"""Pinned NYC Open Data dataset ids.

These were resolved through the Socrata catalog and probed live on 2026-08-20
(see DATA-FINDINGS.md). Re-run `python -m shadeway_pipeline.sources.resolve`
to search the catalog again; eyeball its output before replacing this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from shadeway_pipeline.config import SOCRATA_DOMAIN

CATALOG = "https://api.us.socrata.com/api/catalog/v1"
PINNED = Path(__file__).with_name("datasets.json")

# key -> the search phrase. Keys are what the rest of the pipeline refers to.
DATASET_QUERIES: dict[str, str] = {
    "street_centerline": "NYC Street Centerline CSCL",
    "buildings": "Building Footprints",
    "trees": "2015 Street Tree Census Tree Data",
    "drinking_fountains": "Drinking Fountains",
    "cooling_sites": "Cool It! NYC Cooling Sites",
    "spray_showers": "Cool It! NYC Spray Showers",
    "public_restrooms": "Public Restrooms",
}


def search(phrase: str, limit: int = 5) -> list[dict]:
    response = requests.get(
        CATALOG,
        params={"domains": SOCRATA_DOMAIN, "q": phrase, "limit": limit},
        timeout=60,
    )
    response.raise_for_status()
    return [
        {
            "id": r["resource"]["id"],
            "name": r["resource"]["name"],
            "updated": r["resource"].get("updatedAt", ""),
        }
        for r in response.json()["results"]
    ]


def load_datasets() -> dict[str, str]:
    if not PINNED.exists():
        raise FileNotFoundError(
            "datasets.json missing — run `python -m shadeway_pipeline.sources.resolve`"
        )
    return json.loads(PINNED.read_text())


def main() -> None:
    pinned: dict[str, str] = {}
    for key, phrase in DATASET_QUERIES.items():
        hits = search(phrase)
        print(f"\n## {key}  (query: {phrase!r})")
        for i, hit in enumerate(hits):
            marker = "->" if i == 0 else "  "
            print(f" {marker} {hit['id']}  {hit['name']}")
        if not hits:
            print("    !! NO MATCH — fix the query or pin the id by hand")
            continue
        pinned[key] = hits[0]["id"]
    PINNED.write_text(json.dumps(pinned, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {PINNED}")
    print("EYEBALL THE ARROWS ABOVE. If a top hit is wrong, edit datasets.json.")


if __name__ == "__main__":
    main()
