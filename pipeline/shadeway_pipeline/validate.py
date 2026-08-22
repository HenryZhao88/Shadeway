"""Health report on a built graph + scene. Run it after every rebuild.

Hard checks fail the build. Soft checks are informational — they are how you
notice, on day two, that 60% of your canopy is using a default tau.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa

from shadeway_contracts.tables import (
    ALL_TABLES,
    AZIMUTH_BINS,
    HORIZON_LAYERS,
    EdgeKind,
    SchemaError,
    Side,
    read_table,
    validate_table,
)
from shadeway_pipeline.config import CROSSING_MAX_SPAN_M

MIN_LARGEST_COMPONENT = 0.95


@dataclass
class Check:
    name: str
    ok: bool
    level: str  # "hard" | "soft"
    detail: str


def run_checks(tables: dict[str, pa.Table]) -> list[Check]:
    checks: list[Check] = []

    # --- schemas -----------------------------------------------------------
    problems = []
    for name in ALL_TABLES:
        if name not in tables:
            problems.append(f"{name}: missing")
            continue
        try:
            validate_table(name, tables[name])
        except SchemaError as exc:
            problems.append(str(exc))
    checks.append(
        Check("schemas", not problems, "hard", "; ".join(problems) or "all six conform")
    )
    if problems:
        return checks  # everything below assumes conforming tables

    edges = tables["edges"].to_pydict()
    nodes = tables["nodes"].to_pydict()
    samples = tables["samples"]

    # --- connectivity ------------------------------------------------------
    parent = {int(n): int(n) for n in nodes["node_id"]}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for u, v in zip(edges["u"], edges["v"]):
        ru, rv = find(int(u)), find(int(v))
        if ru != rv:
            parent[ru] = rv
    sizes: dict[int, int] = {}
    for n in parent:
        root = find(n)
        sizes[root] = sizes.get(root, 0) + 1
    fraction = max(sizes.values()) / len(parent) if parent else 0.0
    checks.append(
        Check(
            "connectivity",
            fraction >= MIN_LARGEST_COMPONENT,
            "hard",
            f"largest component {fraction:.3f} of {len(parent)} nodes, "
            f"{len(sizes)} components",
        )
    )

    # --- both sides present ------------------------------------------------
    by_parent: dict[int, set[int]] = {}
    for pid, side, kind in zip(edges["physical_id"], edges["side"], edges["kind"]):
        if kind == EdgeKind.SIDEWALK:
            by_parent.setdefault(int(pid), set()).add(int(side))
    missing = [p for p, s in by_parent.items() if s != {int(Side.LEFT), int(Side.RIGHT)}]
    checks.append(
        Check(
            "both_sides_present",
            not missing,
            "hard",
            f"{len(missing)} of {len(by_parent)} streets lack a left/right pair",
        )
    )

    # --- sample tiling -----------------------------------------------------
    covered = np.zeros(samples.num_rows, dtype=bool)
    overlap = False
    for start, count in zip(edges["sample_start"], edges["sample_count"]):
        block = slice(int(start), int(start) + int(count))
        overlap |= bool(covered[block].any())
        covered[block] = True
    checks.append(
        Check(
            "sample_tiling",
            bool(covered.all()) and not overlap,
            "hard",
            f"{int(covered.sum())}/{samples.num_rows} samples claimed, "
            f"overlap={overlap}",
        )
    )

    # --- crossing sanity ---------------------------------------------------
    spans = [
        length
        for length, kind in zip(edges["length_m"], edges["kind"])
        if kind == EdgeKind.CROSSING
    ]
    absurd = [s for s in spans if s > CROSSING_MAX_SPAN_M + 0.01]
    checks.append(
        Check(
            "crossing_spans",
            not absurd,
            "hard",
            f"{len(spans)} crossings, longest "
            f"{max(spans) if spans else 0:.1f} m, {len(absurd)} over limit",
        )
    )

    # --- soft: canopy sourcing --------------------------------------------
    tau_sources = tables["trees"].column("tau_source").to_pylist()
    defaulted = sum("default" in s.lower() for s in tau_sources)
    frac = defaulted / max(1, len(tau_sources))
    checks.append(
        Check(
            "tau_sourced",
            frac < 0.5,
            "soft",
            f"{defaulted}/{len(tau_sources)} trees ({frac:.0%}) use a default tau",
        )
    )

    # --- soft: widths ------------------------------------------------------
    widths = [w for w in edges["width_m"] if w is not None]
    checks.append(
        Check(
            "sidewalk_widths",
            len(widths) > 0,
            "soft",
            f"{len(widths)}/{len(edges['edge_id'])} edges have a measured width",
        )
    )

    # --- soft: building heights -------------------------------------------
    heights = np.asarray(tables["buildings"].column("height_m").to_pylist())
    ok = len(heights) > 0 and float(np.max(heights)) > 30.0
    checks.append(
        Check(
            "building_heights",
            ok,
            "soft",
            (
                f"n={len(heights)} p50={float(np.median(heights)):.1f}m "
                f"p99={float(np.percentile(heights, 99)):.1f}m "
                f"max={float(np.max(heights)):.1f}m"
            )
            if len(heights)
            else "no buildings",
        )
    )

    # --- soft: horizon cache footprint ------------------------------------
    cache_bytes = samples.num_rows * AZIMUTH_BINS * HORIZON_LAYERS
    checks.append(
        Check(
            "horizon_cache_ram",
            cache_bytes < 2 << 30,
            "soft",
            f"{samples.num_rows} samples -> {cache_bytes / 1e6:.0f} MB of uint8",
        )
    )

    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.level == "hard" and not c.ok for c in checks) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="validate a built graph + scene")
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()

    tables = {name: read_table(args.data / f"{name}.parquet") for name in ALL_TABLES}
    checks = run_checks(tables)

    width = max(len(c.name) for c in checks)
    print(f"\nshadeway validate — {args.data}\n")
    for check in checks:
        mark = "PASS" if check.ok else ("FAIL" if check.level == "hard" else "warn")
        print(f"  [{mark:>4}] {check.name:<{width}}  {check.detail}")
    code = exit_code(checks)
    print("\n" + ("all hard checks passed" if code == 0 else "HARD CHECKS FAILED"))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
