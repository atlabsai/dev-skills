#!/usr/bin/env python3
"""Split a large PR diff into shards for the behavior-parity reviewer.

One parity session cannot cover a large PR: on a 24k-line migration PR a single
session stopped after ~20 tool calls and found none of ~25 known behavior
regressions, while one session per area found most of them. This sorts the
changed files by path (so a directory's files stay next to each other) and cuts
the list into chunks of about TARGET changed lines, at most MAX_SHARDS of them.

Test files are left out of the shards: parity is about product behavior, and
a large test diff would crowd out the code it tests.

Usage:
  plan_parity_shards.py --base REF --out DIR [--head HEAD]

Prints the shard count to stdout. 0 means "don't shard" (the non-test diff is at
or below THRESHOLD); nothing is written then. Otherwise writes DIR/<k>.diff
(k = 1..N) and DIR/SHARDS.txt (the files in each shard). Run from the
repository root.
"""

from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
from pathlib import Path

THRESHOLD = 2000  # changed non-test lines; at or below this, one parity session
TARGET = 1500  # changed lines per shard
MAX_SHARDS = 8
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]*$|_test\.py$"
    r"|\.(test|spec|stories)\.[jt]sx?$"
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_sizes(base: str, head: str) -> tuple[dict[str, int], dict[str, str]]:
    """Non-test changed file -> added + removed lines (binary = 1), and renames new -> old.
    `--numstat -z` gives a rename as an empty path field followed by the old and new paths."""
    sizes: dict[str, int] = {}
    renames: dict[str, str] = {}
    fields = _git("diff", "--numstat", "-z", "-M", base, head).split("\0")
    i = 0
    while i < len(fields) and fields[i]:
        added, removed, path = fields[i].split("\t", 2)
        i += 1
        if not path:
            old, path = fields[i], fields[i + 1]
            renames[path] = old
            i += 2
        if not TEST_PATH.search(path):
            sizes[path] = 1 if added == "-" else int(added) + int(removed)
    return sizes, renames


def plan(sizes: dict[str, int]) -> list[list[str]]:
    """Cut the path-sorted files into chunks; past MAX_SHARDS, chunks grow instead."""
    target = max(TARGET, math.ceil(sum(sizes.values()) / MAX_SHARDS))
    shards: list[list[str]] = [[]]
    load = 0
    for path in sorted(sizes):
        if shards[-1] and load + sizes[path] > target and len(shards) < MAX_SHARDS:
            shards.append([])
            load = 0
        shards[-1].append(path)
        load += sizes[path]
    return shards


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", required=True, help="base ref or SHA, e.g. origin/main"
    )
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    # Diff against the merge base, like `git diff BASE...HEAD` and snapshot_base.py,
    # so a base branch that moved on doesn't leak its own changes into the shards.
    base = _git("merge-base", args.base, args.head).strip()
    sizes, renames = changed_sizes(base, args.head)
    if sum(sizes.values()) <= THRESHOLD:
        print(0)
        return 0
    shards = plan(sizes)
    args.out.mkdir(parents=True, exist_ok=True)
    listing = []
    for k, files in enumerate(shards, start=1):
        # Include each renamed file's old path: git filters paths before rename
        # detection, so without it a moved file shows up as brand new.
        pathspec = files + [renames[f] for f in files if f in renames]
        diff = _git("diff", "-M", base, args.head, "--", *pathspec)
        (args.out / f"{k}.diff").write_text(diff)
        lines = sum(sizes[f] for f in files)
        listing.append(f"# shard {k}: {len(files)} files, {lines} lines")
        listing.extend(files)
    (args.out / "SHARDS.txt").write_text("\n".join(listing) + "\n")
    print(len(shards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
