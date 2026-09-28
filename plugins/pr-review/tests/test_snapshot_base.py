"""Tests for snapshot_base.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import snapshot_base as sb  # noqa: E402


def test_snapshot_holds_base_versions_of_modified_deleted_and_renamed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True)

    monkeypatch.chdir(tmp_path)
    git("init", "-qb", "main")
    for name, body in {"keep": "old\n", "gone": "g\n", "old_name": "r\n" * 20}.items():
        Path(name).write_text(body)
    Path("untouched").write_text("u\n")
    git("add", "-A")
    git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "base")
    git("switch", "-qc", "feature")
    Path("keep").write_text("new\n")
    Path("gone").unlink()
    Path("old_name").rename("new_name")
    Path("added").write_text("a\n")
    git("add", "-A")
    git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "change")

    assert sb.snapshot("main", Path("base")) == 3
    assert Path("base/keep").read_text() == "old\n"
    assert Path("base/gone").read_text() == "g\n"
    assert Path("base/old_name").read_text() == "r\n" * 20
    assert not Path("base/added").exists() and not Path("base/untouched").exists()
    assert sorted(Path("base/INDEX.txt").read_text().splitlines()) == [
        "D gone",
        "M keep",
        "R old_name -> new_name",
    ]
