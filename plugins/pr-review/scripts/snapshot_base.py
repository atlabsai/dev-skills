#!/usr/bin/env python3
"""Write the pre-change copy of every file a PR modifies, deletes or renames.

The behavior-parity reviewer compares old code with new code, and the validator
re-checks those comparisons. Neither has a shell, so they can't `git show` the
base themselves; this puts the base versions on disk where they can Read them.

Layout written to OUT:

  OUT/INDEX.txt        one line per file: "M path", "D path" or "R old -> new"
  OUT/<base path>      the file as it is at the merge base (renames: old path)

Added files are skipped (they have no "before"). The diff is taken against the
merge base, matching `git diff BASE...HEAD`, which is what the reviewers see.

Usage:
  snapshot_base.py --base origin/main --out DIR [--head HEAD]

Run it from the repository root.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def changed_files(merge_base: str, head: str) -> list[tuple[str, str, str | None]]:
    """(status letter, base-side path, new path for renames) for M/D/R entries."""
    out = _git(
        "diff", "--name-status", "-z", "-M", "--diff-filter=MDR", merge_base, head
    )
    fields = out.decode("utf-8", "surrogateescape").split("\0")
    entries: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i][0]
        if status == "R":
            entries.append((status, fields[i + 1], fields[i + 2]))
            i += 3
        else:
            entries.append((status, fields[i + 1], None))
            i += 2
    return entries


def snapshot(base: str, out: Path, head: str = "HEAD") -> int:
    """Write the snapshot; return how many files were captured."""
    merge_base = _git("merge-base", base, head).decode().strip()
    out.mkdir(parents=True, exist_ok=True)
    index_lines: list[str] = []
    captured = 0
    for status, path, new_path in changed_files(merge_base, head):
        index_lines.append(
            f"R {path} -> {new_path}" if new_path else f"{status} {path}"
        )
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(_git("show", f"{merge_base}:{path}"))
            captured += 1
        except subprocess.CalledProcessError:
            # e.g. a submodule entry; the INDEX line still records the change.
            print(f"no base copy of {path}", file=sys.stderr)
    (out / "INDEX.txt").write_text("".join(f"{line}\n" for line in index_lines))
    return captured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    count = snapshot(args.base, args.out, args.head)
    print(f"base snapshot: {count} files in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
