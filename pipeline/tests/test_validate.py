import pyarrow as pa

from shadeway_contracts.fixtures import build_fixture_city
from shadeway_pipeline import validate


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
