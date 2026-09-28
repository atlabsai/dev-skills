#!/usr/bin/env python3
"""Split a large PR diff into area shards for the behavior-parity reviewer.

One parity session cannot cover a large PR: on a 24k-line migration PR a single
session stopped after ~20 tool calls and found none of ~25 known behavior
regressions, while one session per area found most of them. This groups the changed
files by area (their leading path segments), keeps each area whole where it
can, and packs consecutive areas into shards of roughly `--target` diff lines.

Test files are left out of the shards: parity is about product behavior, and
a large test diff would crowd out the code it tests.

Usage:
  plan_parity_shards.py --base REF --out DIR [--head HEAD]
                        [--threshold 2000] [--target 1500] [--max-shards 8]

Prints the shard count to stdout. 0 means "don't shard" (the non-test diff is at or
below --threshold); nothing is written then. Otherwise writes DIR/<k>.diff
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

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]*$|_test\.py$"
    r"|\.(test|spec|stories)\.[jt]sx?$"
)
AREA_DEPTH = 3


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_sizes(base: str, head: str) -> dict[str, int]:
    """Non-test changed file -> added + removed lines (binary files count 1)."""
    sizes: dict[str, int] = {}
    for line in _git("diff", "--numstat", "-M", base, head).splitlines():
        added, removed, path = line.split("\t", 2)
        if " => " in path:  # rename: numstat prints "old => new"
            path = re.sub(r"\{[^}]* => ([^}]*)\}", r"\1", path).split(" => ")[-1]
        if TEST_PATH.search(path):
            continue
        sizes[path] = (int(added) if added != "-" else 1) + (
            int(removed) if removed != "-" else 0
        )
    return sizes


def area_of(path: str) -> str:
    """The file's leading directories (not the file name); top-level files are their own area."""
    return "/".join(path.split("/")[:-1][:AREA_DEPTH]) or path


def plan(sizes: dict[str, int], target: int, max_shards: int) -> list[list[str]]:
    """Pack areas (sorted, so neighbours stay together) into shards."""
    total = sum(sizes.values())
    target = max(target, math.ceil(total / max_shards))
    areas: dict[str, list[str]] = {}
    for path in sorted(sizes):
        areas.setdefault(area_of(path), []).append(path)
    shards: list[list[str]] = [[]]
    load = 0
    for files in areas.values():
        size = sum(sizes[f] for f in files)
        if shards[-1] and load + size > target and len(shards) < max_shards:
            shards.append([])
            load = 0
        # An area bigger than the target is split file by file.
        for f in files:
            if shards[-1] and load + sizes[f] > target and len(shards) < max_shards:
                shards.append([])
                load = 0
            shards[-1].append(f)
            load += sizes[f]
    return [s for s in shards if s]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", required=True, help="base ref or SHA, e.g. origin/main"
    )
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--threshold", type=int, default=2000)
    parser.add_argument("--target", type=int, default=1500)
    parser.add_argument("--max-shards", type=int, default=8)
    args = parser.parse_args()

    # Diff against the merge base, like `git diff BASE...HEAD` and snapshot_base.py,
    # so a base branch that moved on doesn't leak its own changes into the shards.
    base = _git("merge-base", args.base, args.head).strip()
    sizes = changed_sizes(base, args.head)
    if sum(sizes.values()) <= args.threshold:
        print(0)
        return 0
    shards = plan(sizes, args.target, args.max_shards)
    args.out.mkdir(parents=True, exist_ok=True)
    listing = []
    for k, files in enumerate(shards, start=1):
        diff = _git("diff", "-M", base, args.head, "--", *files)
        (args.out / f"{k}.diff").write_text(diff)
        lines = sum(sizes[f] for f in files)
        listing.append(f"# shard {k}: {len(files)} files, {lines} lines")
        listing.extend(files)
    (args.out / "SHARDS.txt").write_text("\n".join(listing) + "\n")
    print(len(shards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
