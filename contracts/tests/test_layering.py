import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN = {
    "server": {"shadeway_pipeline"},
    "pipeline": {"shadeway"},
    "contracts": {"shadeway", "shadeway_pipeline"},
}
# `shadeway.thermal` is pure: no io, no network, no filesystem
PURE_MODULES = ["server/shadeway/thermal"]
IO_MODULES = {"requests", "httpx", "urllib", "pathlib", "open", "socket", "os"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_layers_do_not_reach_into_each_other():
    violations = []
    for pkg, banned in FORBIDDEN.items():
        for path in (ROOT / pkg).rglob("*.py"):
            if "tests" in path.parts:
                continue
            hit = _imports(path) & banned
            if hit:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(hit)}")
    assert not violations, "\n".join(violations)


def test_thermal_model_stays_pure():
    violations = []
    for rel in PURE_MODULES:
        for path in (ROOT / rel).rglob("*.py"):
            hit = _imports(path) & IO_MODULES
            if hit:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(hit)}")
    assert not violations, (
        "thermal/ must be pure functions — move io to weather.py or the api layer:\n"
        + "\n".join(violations)
    )
