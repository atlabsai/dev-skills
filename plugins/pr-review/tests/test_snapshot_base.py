"""Tests for snapshot_base.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import snapshot_base as sb  # noqa: E402


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose `main` has four files, and a `feature` branch that
    modifies one, deletes one, renames one and adds one."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src/keep.py").write_text("def f():\n    return 1\n")
    (root / "src/gone.py").write_text("x = 1\n")
    (root / "src/old_name.py").write_text("y = 2\n" * 20)
    (root / "src/untouched.py").write_text("z = 3\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "feature")
    (root / "src/keep.py").write_text("def f():\n    return 2\n")
    (root / "src/gone.py").unlink()
    (root / "src/old_name.py").rename(root / "src/new_name.py")
    (root / "src/added.py").write_text("new = True\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "change")
    monkeypatch.chdir(root)
    return root


def test_captures_modified_deleted_and_renamed_at_base_paths(repo: Path) -> None:
    out = repo.parent / "base"
    assert sb.snapshot("main", out) == 3
    assert (out / "src/keep.py").read_text() == "def f():\n    return 1\n"
    assert (out / "src/gone.py").read_text() == "x = 1\n"
    assert (out / "src/old_name.py").read_text() == "y = 2\n" * 20


def test_skips_added_and_untouched_files(repo: Path) -> None:
    out = repo.parent / "base"
    sb.snapshot("main", out)
    assert not (out / "src/added.py").exists()
    assert not (out / "src/untouched.py").exists()
    assert not (out / "src/new_name.py").exists()


def test_index_lists_each_change(repo: Path) -> None:
    out = repo.parent / "base"
    sb.snapshot("main", out)
    lines = sorted((out / "INDEX.txt").read_text().splitlines())
    assert lines == [
        "D src/gone.py",
        "M src/keep.py",
        "R src/old_name.py -> src/new_name.py",
    ]


def test_diffs_against_the_merge_base_not_the_base_tip(repo: Path) -> None:
    # main moves on after the branch point; its new change must not leak in.
    git(repo, "switch", "-q", "main")
    (repo / "src/untouched.py").write_text("z = 99\n")
    git(repo, "commit", "-q", "-am", "main moves on")
    git(repo, "switch", "-q", "feature")
    out = repo.parent / "base"
    sb.snapshot("main", out)
    assert not (out / "src/untouched.py").exists()
    assert (out / "src/keep.py").read_text() == "def f():\n    return 1\n"
