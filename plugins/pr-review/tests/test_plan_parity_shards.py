"""Tests for plan_parity_shards.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import plan_parity_shards as pp  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "feature")
    monkeypatch.chdir(root)
    return root


def add_lines(root: Path, path: str, n: int) -> None:
    f = root / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(f"line {i}\n" for i in range(n)))


def commit(root: Path) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "change")
    return git(root, "merge-base", "main", "HEAD").strip()


def test_test_files_are_excluded_from_sizes(repo: Path) -> None:
    add_lines(repo, "app/api/views.py", 10)
    add_lines(repo, "app/api/tests/test_views.py", 500)
    add_lines(repo, "web/src/Button.test.tsx", 500)
    base = commit(repo)
    assert pp.changed_sizes(base, "HEAD") == {"app/api/views.py": 10}


def test_areas_stay_together_and_neighbours_pack(repo: Path) -> None:
    sizes = {
        "app/api/a.py": 400,
        "app/api/b.py": 400,
        "app/engine/c.py": 900,
        "web/src/d.ts": 300,
    }
    shards = pp.plan(sizes, target=1000, max_shards=8)
    assert shards == [
        ["app/api/a.py", "app/api/b.py"],
        ["app/engine/c.py"],
        ["web/src/d.ts"],
    ]


def test_an_oversized_area_is_split_file_by_file() -> None:
    sizes = {f"app/api/f{i}.py": 600 for i in range(3)}
    shards = pp.plan(sizes, target=1000, max_shards=8)
    assert [len(s) for s in shards] == [1, 1, 1]


def test_shard_cap_raises_the_target_instead_of_adding_shards() -> None:
    sizes = {f"area{i}/x/f.py": 1000 for i in range(20)}
    shards = pp.plan(sizes, target=1000, max_shards=4)
    assert len(shards) == 4
    assert sorted(len(s) for s in shards) == [5, 5, 5, 5]


def test_small_diff_is_not_sharded(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_lines(repo, "app/api/views.py", 50)
    base = commit(repo)
    out = repo.parent / "shards"
    sys.argv = ["plan", "--base", base, "--out", str(out)]
    assert pp.main() == 0
    assert capsys.readouterr().out.strip() == "0"
    assert not out.exists()


def test_large_diff_writes_one_diff_per_shard(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_lines(repo, "app/api/views.py", 1200)
    add_lines(repo, "web/src/page.tsx", 1200)
    base = commit(repo)
    out = repo.parent / "shards"
    sys.argv = ["plan", "--base", base, "--out", str(out), "--threshold", "2000"]
    pp.main()
    assert capsys.readouterr().out.strip() == "2"
    assert "app/api/views.py" in (out / "1.diff").read_text()
    assert "web/src/page.tsx" in (out / "2.diff").read_text()
    assert "# shard 1: 1 files, 1200 lines" in (out / "SHARDS.txt").read_text()
