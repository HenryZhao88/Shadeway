
from shadeway_contracts.fixtures import build_fixture_city
from shadeway_pipeline import validate


def _named(checks, name):
    """The one check we care about, by name."""
    match = next((c for c in checks if c.name == name), None)
    assert match is not None, f"no check named {name!r}"
    return match


def test_the_fixture_city_passes_every_hard_check():
    checks = validate.run_checks(build_fixture_city())
    failed = [c for c in checks if c.level == "hard" and not c.ok]
    assert not failed, [f"{c.name}: {c.detail}" for c in failed]


def test_a_disconnected_graph_fails_hard():
    city = build_fixture_city()
    edges = city["edges"]
    # keep only three sidewalk edges: nearly every node becomes unreachable
    # from the rest (the fixture's crossings are self-loops on shared centreline
    # nodes, so deleting crossings alone cannot disconnect it)
    keep = [i for i, k in enumerate(edges.column("kind").to_pylist()) if k == 0][:3]
    city["edges"] = edges.take(keep)
    checks = {c.name: c for c in validate.run_checks(city)}
    assert not checks["connectivity"].ok
    assert checks["connectivity"].level == "hard"


def test_an_empty_but_schema_correct_build_fails_hard():
    from shadeway_contracts.tables import ALL_TABLES

    tables = {name: schema.empty_table() for name, schema in ALL_TABLES.items()}
    checks = validate.run_checks(tables)
    nonempty = _named(checks, "network_nonempty")
    assert not nonempty.ok
    assert nonempty.level == "hard"
    assert validate.exit_code(checks) == 1


def test_a_missing_sidewalk_side_fails_hard():
    city = build_fixture_city()
    edges = city["edges"]
    keep = [
        i
        for i, (k, s) in enumerate(
            zip(edges.column("kind").to_pylist(), edges.column("side").to_pylist())
        )
        if not (k == 0 and s == 1)
    ]
    city["edges"] = edges.take(keep)
    checks = {c.name: c for c in validate.run_checks(city)}
    assert not checks["both_sides_present"].ok


def test_soft_checks_never_fail_the_build():
    checks = validate.run_checks(build_fixture_city())
    soft = [c for c in checks if c.level == "soft"]
    assert soft, "there should be informational checks too"
    # a soft check may be not-ok; that must not be treated as a failure
    assert validate.exit_code(checks) == 0


def test_connectivity_is_judged_per_borough_not_across_the_scope():
    """Manhattan and Brooklyn are two components by construction — the East
    River crossings are rw_type 3, which cscl.py excludes. A scope-wide check
    fails a correct build."""
    import pyarrow as pa

    from shadeway_contracts.fixtures import build_fixture_city
    from shadeway_contracts.tables import NODES

    tables = build_fixture_city()
    nodes = tables["nodes"].to_pydict()
    # Relabel half the nodes and remove every cross-half edge. Scope-wide this
    # is two components of roughly 50%, while each borough remains connected.
    half = len(nodes["node_id"]) // 2
    nodes["borough"] = ["1"] * half + ["3"] * (len(nodes["node_id"]) - half)
    tables["nodes"] = pa.table(nodes, schema=NODES)
    edges = tables["edges"]
    u = edges.column("u").to_pylist()
    v = edges.column("v").to_pylist()
    keep = [i for i, (a, b) in enumerate(zip(u, v)) if (a < half) == (b < half)]
    tables["edges"] = edges.take(keep)

    check = _named(validate.run_checks(tables), "connectivity")
    assert check.ok
    assert "1:" in check.detail and "3:" in check.detail


def test_tau_check_does_not_count_genus_level_sourcing_as_unsourced():
    """"genus default from Quercus palustris (AUF ...)" is a real citation for a
    real measurement on a congener. Substring-matching "default" called it
    unsourced and inflated the reported figure roughly fourfold."""
    import pyarrow as pa

    from shadeway_contracts.fixtures import build_fixture_city
    from shadeway_contracts.tables import TREES

    tables = build_fixture_city()
    trees = tables["trees"].to_pydict()
    n = len(trees["tree_id"])
    trees["tau_source"] = ["genus default from Quercus palustris (AUF)"] * n
    tables["trees"] = pa.table(trees, schema=TREES)

    check = _named(validate.run_checks(tables), "tau_sourced")
    assert check.ok
    assert "0% (0) on the global default" in check.detail
    assert "100% genus-level" in check.detail


def test_tau_check_still_flags_a_genuinely_unsourced_canopy():
    import pyarrow as pa

    from shadeway_contracts.fixtures import build_fixture_city
    from shadeway_contracts.tables import TREES

    tables = build_fixture_city()
    trees = tables["trees"].to_pydict()
    n = len(trees["tree_id"])
    trees["tau_source"] = ["global default — midpoint of the band"] * n
    tables["trees"] = pa.table(trees, schema=TREES)

    check = _named(validate.run_checks(tables), "tau_sourced")
    assert not check.ok


def test_offsets_check_replaces_the_unreachable_width_check():
    """`width_m` comes from planimetric data that serves null geometry through
    the API, so warning about it every build reported a decision as unfinished
    work. What the offsets actually came from is checkable, and matters more."""
    from shadeway_contracts.fixtures import build_fixture_city

    checks = validate.run_checks(build_fixture_city())
    names = {c.name for c in checks}
    assert "offsets_from_streetwidth" in names
    assert "sidewalk_widths" not in names
