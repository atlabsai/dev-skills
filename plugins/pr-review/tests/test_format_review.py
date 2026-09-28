"""Tests for format_review.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import format_review as fr  # noqa: E402

ENV = {
    "REPO": "acme/app",
    "BRANCH": "feature",
    "PR": "7",
    "PR_TITLE": "Add thing",
    "FAILED_REVIEWERS": "",
    "REVIEWER_COUNT": "5",
    "RUNTIME": "42",
    "RERUN_HINT": "",
}


def finding(**overrides: object) -> dict:
    base = {
        "title": "A bug",
        "file": "app.py",
        "line_start": 2,
        "code_snippet": "x = 1\ny = x / 0\nz = 3",
        "explanation": "Divides by zero.",
        "severity": "critical",
        "validator_verdict": "confirmed",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def in_tmp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app.py").write_text("x = 1\ny = x / 0\nz = 3\n")
    monkeypatch.chdir(tmp_path)


def test_orders_by_confidence_within_severity_and_numbers_across_sections() -> None:
    findings = [
        finding(title="No confidence"),
        finding(title="Low", confidence="low", confidence_basis="Unverified caller."),
        finding(title="High", confidence="high", confidence_basis="Traced it."),
        finding(title="Warn", severity="warning", confidence="medium"),
    ]
    out = fr.build_comment(findings, {}, ENV)
    titles = [line for line in out.splitlines() if line.startswith("### ")]
    assert titles == [
        "### 1. High",
        "### 2. Low",
        "### 3. No confidence",
        "### 4. Warn",
    ]
    assert "**Confidence:** 🟢 high — Traced it." in out
    assert "**Confidence:** 🟠 medium\n" in out


def test_marks_the_flagged_line_and_links_to_github() -> None:
    out = fr.build_comment([finding()], {}, ENV)
    assert "y = x / 0  # ← issue here" in out
    assert "[`app.py:2`](https://github.com/acme/app/blob/feature/app.py#L2)" in out


def test_local_mode_renders_plain_references() -> None:
    out = fr.build_comment([finding()], {}, {**ENV, "REPO": "", "PR": ""})
    assert "`app.py:2`" in out and "https://github.com/acme" not in out
    assert out.startswith("🤖 PR Review — Add thing")


def test_pre_existing_notes_are_dropped_but_warnings_kept() -> None:
    findings = [
        finding(title="Old note", severity="note", validator_verdict="pre_existing"),
        finding(
            title="Old warning", severity="warning", validator_verdict="pre_existing"
        ),
    ]
    out = fr.build_comment(findings, {}, ENV)
    assert "Old note" not in out
    assert "📌 [Pre-existing] Old warning" in out


def test_summary_is_neutral_about_merging() -> None:
    out = fr.build_comment([finding()], {"pr_summary": "Adds a thing"}, ENV)
    assert "Adds a thing. 1 critical issue flagged." in out
    assert "before merge" not in out


def test_contour_links_and_manual_tests_put_existing_risk_first() -> None:
    impact = {
        "contours": [
            {
                "name": "Checkout",
                "file_refs": [{"file": "app.py", "line": 2}],
                "risk_explanation": "Callers rely on it.",
            }
        ],
        "manual_test_targets": [
            {"priority": "new_path", "description": "Try the new thing"},
            {"priority": "existing_risk", "description": "Re-run checkout"},
        ],
    }
    out = fr.build_comment([], impact, ENV)
    assert "**Checkout** — [`app.py:2`]" in out
    assert out.index("Re-run checkout") < out.index("Try the new thing")


def test_malformed_input_degrades_to_empty(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert fr.load_json(str(bad), []) == []
    assert fr.load_json(str(tmp_path / "missing.json"), {}) == {}


def test_cli_reads_the_run_dir_and_reports_missing_reviewers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "run"
    (run / "pr-context").mkdir(parents=True)
    (run / "reviews").mkdir()
    (run / "pr-context" / "meta.json").write_text(
        '{"title": "My branch", "started_at": 1}'
    )
    (run / "reviews" / "bugs.txt").write_text("[]")
    (run / "reviews" / "arch.txt").write_text("")  # exited 0 but wrote nothing
    (run / "validated.json").write_text("[]")

    assert fr.main(["--run-dir", str(run), "--reviewers", "bugs arch prod"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("🤖 PR Review — My branch")
    assert "3 reviewers" in out
    assert "produced no output: arch, prod" in out
    assert (run / "comment.md").read_text() == out


def test_malformed_or_differently_cased_confidence_does_not_crash() -> None:
    findings = [
        finding(title="List", confidence=["high"]),
        finding(title="Cased", confidence="High"),
    ]
    out = fr.build_comment(findings, {}, ENV)
    assert "### 1. Cased" in out and "**Confidence:** 🟢 high" in out
    assert "### 2. List" in out


def test_clean_pr_has_no_doubled_separator() -> None:
    out = fr.build_comment([], {}, ENV)
    assert "---\n\n---" not in out
