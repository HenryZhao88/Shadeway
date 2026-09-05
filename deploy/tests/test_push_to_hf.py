"""Exercise deployment staging with a local git stand-in; never push a Space."""

import os
import shutil
import subprocess
from pathlib import Path


def test_hf_stage_includes_the_docker_city_verifier(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = Path(__file__).resolve().parents[2]
    for name in ("Dockerfile", ".dockerignore", "package.json", "package-lock.json",
                 "deploy/push-to-hf.sh", "deploy/verify_city.py", "deploy/huggingface/README.md"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    for package in ("contracts", "server", "web"):
        (root / package).mkdir()
    city = root / "data/nyc"
    city.mkdir(parents=True)
    (city / "edges.parquet").touch()
    (city / "horizon.npz").touch()
    commands = tmp_path / "bin"
    commands.mkdir()
    git = commands / "git"
    git.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = "lfs" ] && [ "$2" = "track" ]; then touch .gitattributes; fi\n'
        'if [ "$1" = "push" ]; then\n'
        '  test -f deploy/verify_city.py || exit 91\n'
        '  cmp deploy/verify_city.py "$SOURCE_VERIFIER" || exit 92\n'
        '  test -f data/nyc/horizon.npz || exit 93\n'
        '  echo "verified local deployment stage"\n'
        'fi\n'
    )
    git.chmod(0o755)
    shutil.copyfile(git, commands / "git-lfs")
    (commands / "git-lfs").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{commands}:{os.environ['PATH']}",
        "OUT": "data/nyc",
        "SOURCE_VERIFIER": str(root / "deploy/verify_city.py"),
    }
    result = subprocess.run(
        ["bash", str(root / "deploy/push-to-hf.sh"), "local/test"],
        env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified local deployment stage" in result.stdout
