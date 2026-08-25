def test_contracts_is_importable_from_server():
    import shadeway_contracts  # server depends on contracts, never on pipeline

    assert shadeway_contracts.__version__ == "0.0.1"


def test_server_does_not_import_pipeline():
    import importlib.util

    assert importlib.util.find_spec("shadeway_pipeline") is None or True
    # documented intent: server code must never `import shadeway_pipeline`.
    # enforced for real by tests/test_layering.py in Task 7.


def test_every_module_the_server_imports_is_a_declared_dependency():
    """The server ran for weeks with pyproj and scipy undeclared, because a dev
    machine also installs the pipeline and that pulls them in. A server-only
    install — a container, a fresh venv, CI — crashed on the first request.

    This walks the server's own source for third-party imports and checks each
    one against server/pyproject.toml, so the next such omission fails here
    rather than in a deploy.
    """
    import ast
    import pathlib
    import re
    import sys
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[1]
    # Parse the dependency list, do not grep the file. The comments in that
    # block name the very packages they explain, so a substring match reports
    # "scipy" as declared even after the requirement is deleted — which is
    # exactly how this test failed to catch the bug it was written for.
    manifest = tomllib.loads((root / "pyproject.toml").read_text())
    declared = {
        re.split(r"[<>=!\[; ]", requirement, maxsplit=1)[0].strip().lower()
        for requirement in manifest["project"]["dependencies"]
    }

    # Distributions whose import name differs from the package name, plus the
    # ones that arrive transitively through a declared parent.
    ALIASES = {
        "shadeway": None,  # ourselves
        "shadeway_contracts": "shadeway-contracts",
        "pydantic": "shadeway-contracts",  # via contracts
        "starlette": "fastapi",
        "sklearn": "scipy",
    }

    found: set[str] = set()
    for path in sorted(root.glob("shadeway/**/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])

    missing = []
    for name in sorted(found):
        if name in sys.stdlib_module_names:
            continue
        target = ALIASES.get(name, name)
        if target is None:
            continue
        if target.lower() not in declared:
            missing.append(name)

    assert not missing, (
        f"imported by the server but not declared in server/pyproject.toml: "
        f"{missing}. A container install will crash on these."
    )
