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

    # Schema equality says nothing about whether a build contains a city. An
    # empty set of six correctly typed tables used to pass every hard check
    # because vacuous `all()` calls and a connectivity default of 1.0 all read
    # as success.
    row_counts = {
        "nodes": len(nodes["node_id"]),
        "edges": len(edges["edge_id"]),
        "samples": samples.num_rows,
    }
    network_nonempty = all(row_counts.values())
    checks.append(
        Check(
            "network_nonempty",
            network_nonempty,
            "hard",
            " · ".join(f"{name}={count}" for name, count in row_counts.items()),
        )
    )
    if not network_nonempty:
        return checks

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

    # Connectivity is checked PER BOROUGH, not across the whole scope.
    #
    # Manhattan and Brooklyn are not walkable to each other in this model: the
    # East River crossings are all rw_type 3, which cscl.py excludes. So a
    # correct manhattan+brooklyn build is two large components, and a
    # scope-wide check would report 0.673 and fail a build that is fine. What
    # actually matters is that you can walk anywhere within a borough.
    boroughs = [str(b) for b in nodes["borough"]]
    node_ids = [int(n) for n in nodes["node_id"]]
    per_borough: dict[str, dict[int, int]] = {}
    for node_id, borough in zip(node_ids, boroughs):
        per_borough.setdefault(borough, {})
        root = find(node_id)
        per_borough[borough][root] = per_borough[borough].get(root, 0) + 1

    worst_name, worst_fraction = "", 1.0
    for borough, roots in sorted(per_borough.items()):
        total = sum(roots.values())
        fraction = max(roots.values()) / total if total else 0.0
        if fraction <= worst_fraction:
            worst_name, worst_fraction = borough, fraction
    detail = " · ".join(
        f"{borough}: {max(roots.values()) / sum(roots.values()):.3f} "
        f"of {sum(roots.values())}"
        for borough, roots in sorted(per_borough.items())
    )
    checks.append(
        Check(
            "connectivity",
            worst_fraction >= MIN_LARGEST_COMPONENT,
            "hard",
            f"largest component per borough — {detail}"
            + (f" (worst: {worst_name})" if len(per_borough) > 1 else "")
            + f" · {len(sizes)} components scope-wide",
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
    #
    # Three tiers, not two. Matching on the substring "default" counted every
    # genus-level entry as unsourced, because those sources read "genus default
    # from Quercus palustris (AUF ...)" — a real citation for a real measurement
    # on a congener. That reported 23% defaulted when the truly unsourced share
    # was 6%, which is the difference between a soft warning worth acting on and
    # one you learn to ignore.
    tau_sources = tables["trees"].column("tau_source").to_pylist()
    total_trees = max(1, len(tau_sources))
    unsourced = sum(s.lower().startswith("global default") for s in tau_sources)
    by_genus = sum(
        "genus default" in s.lower() and not s.lower().startswith("global default")
        for s in tau_sources
    )
    by_species = total_trees - unsourced - by_genus
    frac = unsourced / total_trees
    checks.append(
        Check(
            "tau_sourced",
            frac < 0.15,
            "soft",
            f"{by_species / total_trees:.0%} species-level · "
            f"{by_genus / total_trees:.0%} genus-level · "
            f"{frac:.0%} ({unsourced}) on the global default",
        )
    )

    # --- soft: offsets -----------------------------------------------------
    #
    # NOT a sidewalk-width check any more. `width_m` is nullable and sourced
    # from planimetric sidewalk data, and both NYC sidewalk datasets are Socrata
    # "map" assets that serve null geometry through the API (DATA-FINDINGS #8) —
    # so it is null on every edge by design, and warning about that every build
    # was reporting a decision as if it were unfinished work.
    #
    # What IS worth checking is the thing those datasets were wanted for: that
    # the per-segment offsets came from CSCL `streetwidth` rather than falling
    # back to the constant. A build where most streets hit the fallback has lost
    # the per-street offsets, and on a wide avenue that offset is the difference
    # between the two sidewalks being 13 m and 25 m apart — which is the whole
    # side-of-street claim.
    from shadeway_pipeline.config import SIDEWALK_HALF_WIDTH_M, offset_for

    fallback_span = 2.0 * (offset_for(None) - SIDEWALK_HALF_WIDTH_M)
    street_spans = _street_spans(edges)
    varied = [gap for gap in street_spans if abs(gap - fallback_span) > 0.5]
    share = len(varied) / len(street_spans) if street_spans else 0.0
    checks.append(
        Check(
            "offsets_from_streetwidth",
            share >= 0.80,
            "soft",
            f"{share:.0%} of streets got a per-segment offset from CSCL "
            f"streetwidth; the rest fell back to {fallback_span:.1f} m",
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
    # Two uint8 horizon layers plus one uint8 canopy-transmissivity layer.
    cache_bytes = samples.num_rows * AZIMUTH_BINS * (HORIZON_LAYERS + 1)
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


def _street_spans(edges) -> list[float]:
    """Distance between the two sidewalks of each street, in metres.

    Recovered from geometry rather than trusted from a column: the left and
    right edges of one `physical_id` are offset from the same centerline, so the
    gap between their midpoints is twice the offset that was applied.
    """
    import shapely

    from shadeway_contracts.tables import EdgeKind, Side

    sides: dict[int, dict[int, object]] = {}
    for pid, side, kind, wkb in zip(
        edges["physical_id"], edges["side"], edges["kind"], edges["geom_wkb"]
    ):
        if kind != EdgeKind.SIDEWALK:
            continue
        sides.setdefault(int(pid), {})[int(side)] = wkb

    spans: list[float] = []
    for pair in sides.values():
        left, right = pair.get(int(Side.LEFT)), pair.get(int(Side.RIGHT))
        if left is None or right is None:
            continue
        a = shapely.from_wkb(left).interpolate(0.5, normalized=True)
        b = shapely.from_wkb(right).interpolate(0.5, normalized=True)
        spans.append(float(a.distance(b)))
    return spans


if __name__ == "__main__":
    main()
