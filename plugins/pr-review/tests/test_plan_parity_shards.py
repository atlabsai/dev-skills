"""Tests for plan_parity_shards.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import plan_parity_shards as pp  # noqa: E402


def test_path_sorted_chunks_and_the_shard_cap() -> None:
    assert pp.plan({"b/y.py": 900, "a/x.py": 900, "c/z.py": 400}) == [
        ["a/x.py"],
        ["b/y.py", "c/z.py"],
    ]
    capped = pp.plan({f"d{i:02}/f.py": 1000 for i in range(20)})
    assert len(capped) == pp.MAX_SHARDS and sum(map(len, capped)) == 20


def test_shards_diff_against_the_merge_base_and_skip_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True)

    def commit(files: dict[str, int]) -> None:
        for path, n in files.items():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("x\n" * n)
        git("add", "-A")
        git("-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "c")

    monkeypatch.chdir(tmp_path)
    git("init", "-qb", "main")
    commit({"README.md": 1})
    git("switch", "-qc", "feature")
    commit({"app/views.py": 1200, "web/page.tsx": 1200, "app/tests/test_v.py": 3000})
    git("switch", "-q", "main")
    commit({"other/on_main.py": 5000})  # main moves on after the branch point
    git("switch", "-q", "feature")

    sys.argv = ["plan", "--base", "main", "--out", "shards"]
    pp.main()
    assert capsys.readouterr().out.strip() == "2"
    listing = Path("shards/SHARDS.txt").read_text()
    assert "on_main" not in listing and "test_v" not in listing
    assert "app/views.py" in Path("shards/1.diff").read_text()
