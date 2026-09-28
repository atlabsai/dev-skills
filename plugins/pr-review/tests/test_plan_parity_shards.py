"""Tests for plan_parity_shards.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import plan_parity_shards as pp  # noqa: E402


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def write_and_commit(root: Path, files: dict[str, int]) -> None:
    for path, n in files.items():
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(f"line {i}\n" for i in range(n)))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "change")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    write_and_commit(root, {"README.md": 1})
    git(root, "switch", "-q", "-c", "feature")
    monkeypatch.chdir(root)
    return root


def run(out: Path, capsys: pytest.CaptureFixture[str]) -> str:
    sys.argv = ["plan", "--base", "main", "--out", str(out)]
    pp.main()
    return capsys.readouterr().out.strip()


def test_files_in_one_directory_stay_together_even_for_shallow_paths() -> None:
    # The area is the directory, not the first 3 path segments incl. the file.
    sizes = {"app/a/x.py": 600, "app/b/y.py": 300, "app/b/z.py": 300}
    assert pp.plan(sizes, target=1000, max_shards=8) == [
        ["app/a/x.py"],
        ["app/b/y.py", "app/b/z.py"],
    ]


def test_an_oversized_area_is_split_file_by_file() -> None:
    sizes = {f"app/api/f{i}.py": 600 for i in range(3)}
    assert [len(s) for s in pp.plan(sizes, target=1000, max_shards=8)] == [1, 1, 1]


def test_shard_cap_raises_the_target_instead_of_adding_shards() -> None:
    sizes = {f"area{i}/x/f.py": 1000 for i in range(20)}
    shards = pp.plan(sizes, target=1000, max_shards=4)
    assert sorted(len(s) for s in shards) == [5, 5, 5, 5]


def test_small_diff_is_not_sharded(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_and_commit(repo, {"app/api/views.py": 50})
    out = repo.parent / "shards"
    assert run(out, capsys) == "0"
    assert not out.exists()


def test_large_diff_shards_against_the_merge_base_and_skips_tests(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_and_commit(
        repo,
        {
            "app/api/views.py": 1200,
            "web/src/page.tsx": 1200,
            "app/api/tests/test_views.py": 3000,
        },
    )
    git(repo, "switch", "-q", "main")
    write_and_commit(repo, {"other/moved/on.py": 5000})  # main moves on
    git(repo, "switch", "-q", "feature")

    out = repo.parent / "shards"
    assert run(out, capsys) == "2"
    listing = (out / "SHARDS.txt").read_text()
    assert "other/moved" not in listing and "test_views" not in listing
    assert "app/api/views.py" in (out / "1.diff").read_text()
    assert "web/src/page.tsx" in (out / "2.diff").read_text()
