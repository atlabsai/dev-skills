#!/usr/bin/env python3
"""Deterministically format a pr-review comment from validated findings + impact analysis.

Turning two JSON files into markdown is pure data-shaping: no model, no tool
loop, no cold start. An LLM formatter doing this job took ~10 minutes per run;
this takes milliseconds and never drifts from the contract.

Used by both the local /pr-review command and the GitHub Actions workflow,
which lay out a run directory the same way:

  <run-dir>/pr-context/meta.json   {"title", "body", "started_at": unix seconds}
  <run-dir>/reviews/<name>.txt     one file per reviewer that produced output
  <run-dir>/validated.json         the validator's JSON array
  <run-dir>/impact.json            the impact analyst's JSON object

Usage:
  format_review.py --run-dir DIR --reviewers "bugs arch quality simplify prod"
                   [--pr N --repo OWNER/REPO --branch BRANCH] [--rerun-hint TEXT]

Writes <run-dir>/comment.md and prints it. A reviewer listed in --reviewers
with no output file is reported as failed. With --repo and --branch, file
references become GitHub links; otherwise plain path:line.

Contour snippets are read from the working directory, which must be the
checked-out PR head.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

GITHUB_COMMENT_LIMIT = 65535

SEVERITY_ORDER = ["critical", "warning", "note"]

# (label, open by default)
SEVERITY_HEADERS = {
    "critical": ("🔴 Critical", True),
    "warning": ("🟡 Warnings", False),
    "note": ("🔵 Notes", False),
}

# Confidence level -> (sort rank, badge). Within a severity section,
# most-certain findings first; findings without a confidence (e.g. from a
# custom validator) sort last and render no badge.
CONFIDENCE_LEVELS = {
    "high": (0, "🟢 high"),
    "medium": (1, "🟠 medium"),
    "low": (2, "⚪ low"),
}
UNRANKED = (len(CONFIDENCE_LEVELS), "")


def confidence_level(finding: dict) -> tuple[int, str]:
    """(sort rank, badge) for a finding; unranked with no badge if absent."""
    return CONFIDENCE_LEVELS.get(finding.get("confidence") or "", UNRANKED)


LANG_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".rs": "rust",
    ".swift": "swift",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".sql": "sql",
    ".sh": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
}

HASH_COMMENT = {"python", "ruby", "bash", "yaml"}
SLASH_COMMENT = {
    "typescript", "javascript", "go", "java", "kotlin", "rust",
    "swift", "php", "csharp", "c", "cpp",
}  # fmt: skip


def warn(msg: str) -> None:
    print(f"::warning::format_review: {msg}", file=sys.stderr)


def load_json(path: str, default: Any) -> Any:
    """Parse a JSON file, degrading to `default` with a warning on any failure.

    A malformed stage output should produce a degraded-but-posted review, not
    a crash that leaves the PR with no feedback at all.
    """
    if not path or not os.path.isfile(path):
        warn(f"input file missing: {path!r}; using empty default")
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        warn(f"could not parse {path!r}: {exc}; using empty default")
        return default


def lang_for(file_path: str) -> str:
    _, ext = os.path.splitext(file_path or "")
    return LANG_BY_EXT.get(ext.lower(), "")


def marker_for(lang: str) -> str:
    if lang in HASH_COMMENT:
        return "# ← issue here"
    if lang in SLASH_COMMENT:
        return "// ← issue here"
    return ""


def fenced(code: str, lang: str) -> str:
    body = (code or "").rstrip("\n")
    return f"```{lang}\n{body}\n```"


def file_ref(repo: str, branch: str, file_path: str, line: Any) -> str:
    has_line = line not in (None, "", 0)
    label = f"`{file_path}:{line}`" if has_line else f"`{file_path}`"
    if not (repo and branch):
        return label
    frag = f"#L{line}" if has_line else ""
    return f"[{label}](https://github.com/{repo}/blob/{branch}/{file_path}{frag})"


def read_lines(file_path: str) -> list[str]:
    if not file_path or not os.path.isfile(file_path):
        return []
    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return []


def to_line_no(line: Any) -> int:
    try:
        return int(line)
    except (TypeError, ValueError):
        return 0


def read_snippet(file_path: str, line: Any, before: int = 2, after: int = 3) -> str:
    """A few lines around `line` from the checked-out repo; empty on failure."""
    line_no = to_line_no(line)
    lines = read_lines(file_path)
    if line_no < 1 or not lines:
        return ""
    start = max(0, line_no - 1 - before)
    return "".join(lines[start : min(len(lines), line_no + after)])


def mark_problematic_line(snippet: str, file_path: str, line_start: Any) -> str:
    """Append '← issue here' to the snippet line that matches the flagged source line.

    Matching against the authoritative line read from disk (not a snippet
    offset) puts the marker on the exact flagged line even when the snippet
    starts a few lines earlier. Unchanged if the line can't be located.
    """
    marker = marker_for(lang_for(file_path))
    line_no = to_line_no(line_start)
    lines = read_lines(file_path)
    if not snippet or not marker or not (0 < line_no <= len(lines)):
        return snippet
    target = lines[line_no - 1].strip()
    if not target:
        return snippet
    out: list[str] = []
    marked = False
    for line in snippet.splitlines():
        if not marked and line.strip() == target:
            out.append(f"{line.rstrip()}  {marker}")
            marked = True
        else:
            out.append(line)
    return "\n".join(out)


def details(header: str, body: str, is_open: bool) -> str:
    open_attr = " open" if is_open else ""
    return f"<details{open_attr}>\n<summary>\n\n{header}\n\n</summary>\n\n{body}\n\n</details>"


def title_prefix(finding: dict) -> str:
    return {
        "edge_case": "~ [Edge Case] ",
        "pre_existing": "📌 [Pre-existing] ",
    }.get(finding.get("validator_verdict") or "", "")


def in_section(finding: dict, severity: str) -> bool:
    """Pre-existing notes are dropped; everything else renders under its severity."""
    if finding.get("severity") != severity:
        return False
    return not (
        finding.get("validator_verdict") == "pre_existing" and severity == "note"
    )


def render_finding(finding: dict, number: int, repo: str, branch: str) -> str:
    file_path = finding.get("file") or ""
    line_start = finding.get("line_start")
    lang = lang_for(file_path)
    parts = [
        f"### {number}. {title_prefix(finding)}{finding.get('title') or '(untitled finding)'}"
    ]

    if file_path:
        parts.append(file_ref(repo, branch, file_path, line_start))

    _, badge = confidence_level(finding)
    if badge:
        basis = (finding.get("confidence_basis") or "").strip()
        parts.append(f"**Confidence:** {badge}" + (f" — {basis}" if basis else ""))

    snippet = finding.get("code_snippet") or read_snippet(file_path, line_start)
    if snippet:
        parts.append(
            fenced(mark_problematic_line(snippet, file_path, line_start), lang)
        )

    if finding.get("explanation"):
        parts.append(finding["explanation"])

    if finding.get("suggested_fix"):
        parts.append(f"**Suggested fix:** {finding['suggested_fix']}")
    if finding.get("suggested_fix_code"):
        parts.append(fenced(finding["suggested_fix_code"], lang))

    verdict = finding.get("validator_verdict")
    note = finding.get("validator_note")
    if verdict == "edge_case":
        parts.append(f"> ~ edge case — {note}" if note else "> ~ edge case")
    elif verdict == "pre_existing":
        parts.append(
            "> 📌 pre-existing — in code you touched, not introduced by this PR"
        )
    elif note:
        parts.append(f"> {note}")

    return "\n\n".join(parts)


def render_severity_section(
    findings: list[dict], severity: str, start: int, repo: str, branch: str
) -> tuple[str, int]:
    group = sorted(
        (f for f in findings if in_section(f, severity)),
        key=lambda f: confidence_level(f)[0],
    )
    if not group:
        return "", start
    label, is_open = SEVERITY_HEADERS[severity]
    blocks = [render_finding(f, start + i, repo, branch) for i, f in enumerate(group)]
    section = details(f"## {label} ({len(group)})", "\n\n---\n\n".join(blocks), is_open)
    return section, start + len(group)


def render_contours(impact: dict, repo: str, branch: str) -> str:
    contours = impact.get("contours") or []
    header = (
        f"## 📍 Integration Contours ({impact.get('contour_count', len(contours))})"
    )
    if not contours:
        return details(header, "_No integration contours identified._", True)

    blocks: list[str] = []
    for contour in contours:
        refs = [r for r in contour.get("file_refs") or [] if r.get("file")]
        links = ", ".join(
            file_ref(repo, branch, r["file"], r.get("line")) for r in refs
        )
        block = [
            f"**{contour.get('name') or '(unnamed contour)'}**"
            + (f" — {links}" if links else "")
        ]
        if refs:
            snippet = read_snippet(refs[0]["file"], refs[0].get("line"))
            if snippet:
                block.append(fenced(snippet, lang_for(refs[0]["file"])))
        if contour.get("risk_explanation"):
            block.append(contour["risk_explanation"])
        blocks.append("\n\n".join(block))
    return details(header, "\n\n".join(blocks), True)


def render_manual_tests(impact: dict) -> str:
    targets = impact.get("manual_test_targets") or []
    if not targets:
        return ""
    ordered = sorted(targets, key=lambda t: t.get("priority") != "existing_risk")
    bullets = [
        f"- {'⚠️' if t.get('priority') == 'existing_risk' else '🆕'} {(t.get('description') or '').strip()}"
        for t in ordered
    ]
    legend = "⚠️ = existing behaviour at risk &nbsp;|&nbsp; 🆕 = new path"
    return details(
        "## ✅ Manual Test Targets", legend + "\n\n" + "\n".join(bullets), True
    )


def render_test_gaps(impact: dict) -> str:
    gaps = impact.get("test_gaps") or []
    if not gaps:
        return ""
    return details("## 🧪 Test Gaps", "\n".join(f"- {g}" for g in gaps), False)


def risk_sentence(critical: int, warning: int) -> str:
    if critical:
        return f"{critical} critical {'issue' if critical == 1 else 'issues'} flagged."
    if warning:
        return f"No critical issues; {warning} {'warning' if warning == 1 else 'warnings'} to consider."
    return "No critical issues or warnings flagged."


def build_comment(
    findings: list[dict],
    impact: dict,
    env: dict[str, str],
    drop_test_gaps: bool = False,
    drop_notes: bool = False,
) -> str:
    repo, branch, pr = env["REPO"], env["BRANCH"], env["PR"]
    title = env["PR_TITLE"]
    failed = [r.strip() for r in env["FAILED_REVIEWERS"].split(",") if r.strip()]

    shown = [f for f in findings if f.get("validator_verdict") != "pre_existing"]
    critical = sum(1 for f in findings if in_section(f, "critical"))
    warning = sum(1 for f in findings if in_section(f, "warning"))
    contour_count = impact.get("contour_count", len(impact.get("contours") or []))

    heading = f"PR #{pr}: {title}" if pr else title
    header = [
        f"🤖 PR Review — {heading}",
        f"{env['REVIEWER_COUNT']} reviewers · validated · {contour_count} contours · {len(shown)} findings",
    ]
    if failed:
        header.append(
            f"⚠️ Reviewer(s) produced no output: {', '.join(failed)}. Results may be incomplete."
        )

    summary = (impact.get("pr_summary") or "").strip() or title.strip()
    if summary and not summary.endswith((".", "!", "?")):
        summary += "."
    sections = [
        "\n".join(header),
        f"{summary} {risk_sentence(critical, warning)}".strip(),
        "---",
    ]

    number = 1
    for severity in SEVERITY_ORDER[:2] if drop_notes else SEVERITY_ORDER:
        section, number = render_severity_section(
            findings, severity, number, repo, branch
        )
        if section:
            sections.append(section)

    sections.append("---")
    sections.append(render_contours(impact, repo, branch))
    for block in (
        render_manual_tests(impact),
        "" if drop_test_gaps else render_test_gaps(impact),
    ):
        if block:
            sections.append(block)

    footer = ["---"]
    if env["RERUN_HINT"]:
        footer.append(env["RERUN_HINT"])
    runtime = f" · {env['RUNTIME']}s" if env["RUNTIME"] else ""
    footer.append(
        f"_Generated by [pr-review](https://github.com/atlabsai/dev-skills){runtime}_"
    )
    sections.append("\n\n".join(footer))
    return "\n\n".join(sections) + "\n"


def has_output(run_dir: str, reviewer: str) -> bool:
    """The stage contract is a non-empty output file, not an exit code."""
    path = os.path.join(run_dir, "reviews", f"{reviewer}.txt")
    return os.path.isfile(path) and os.path.getsize(path) > 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--reviewers", required=True, help="space-separated reviewer names"
    )
    parser.add_argument("--pr", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--rerun-hint", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir
    reviewers = args.reviewers.split()

    meta = load_json(os.path.join(run_dir, "pr-context", "meta.json"), {})
    meta = meta if isinstance(meta, dict) else {}
    started_at = meta.get("started_at")
    failed = [name for name in reviewers if not has_output(run_dir, name)]
    env = {
        "REPO": args.repo,
        "BRANCH": args.branch,
        "PR": args.pr,
        "PR_TITLE": str(meta.get("title") or ""),
        "FAILED_REVIEWERS": ",".join(failed),
        "REVIEWER_COUNT": str(len(reviewers)),
        "RUNTIME": str(int(time.time()) - int(started_at))
        if isinstance(started_at, int)
        else "",
        "RERUN_HINT": args.rerun_hint,
    }

    findings = load_json(os.path.join(run_dir, "validated.json"), [])
    impact = load_json(os.path.join(run_dir, "impact.json"), {})
    if not isinstance(findings, list):
        warn("validated findings is not a JSON array; using an empty list")
        findings = []
    if not isinstance(impact, dict):
        warn("impact analysis is not a JSON object; using an empty object")
        impact = {}

    # GitHub rejects comments over its size limit: drop Test Gaps, then Notes,
    # then truncate as a last resort.
    comment = build_comment(findings, impact, env)
    if len(comment) > GITHUB_COMMENT_LIMIT:
        warn("comment over GitHub's limit; dropping Test Gaps")
        comment = build_comment(findings, impact, env, drop_test_gaps=True)
    if len(comment) > GITHUB_COMMENT_LIMIT:
        warn("comment still over the limit; dropping Notes")
        comment = build_comment(
            findings, impact, env, drop_test_gaps=True, drop_notes=True
        )
    if len(comment) > GITHUB_COMMENT_LIMIT:
        comment = (
            comment[: GITHUB_COMMENT_LIMIT - 40].rstrip()
            + "\n\n_…comment truncated._\n"
        )

    with open(os.path.join(run_dir, "comment.md"), "w", encoding="utf-8") as fh:
        fh.write(comment)
    sys.stdout.write(comment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
