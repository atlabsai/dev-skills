#!/usr/bin/env python3
"""Rewrite a model's final message in place as the JSON value it contains.

Engines that capture a stage's final message (Codex's --output-last-message)
get whatever the model said: DISMISSED/MERGED log lines before the array, a
```json fence around it, a sentence after it. The formatter needs the bare
JSON, so this keeps the payload's JSON array or object and drops the rest
(see extract() for how the payload is picked).

Usage: extract_json.py FILE [array|object]
Exits 1, leaving FILE untouched, if no JSON value of that type is found.
"""

from __future__ import annotations

import json
import sys


def extract(text: str, kind: str) -> object | None:
    """The top-level JSON value of `kind` in `text`.

    Scanning skips over each value it parses, so a value nested inside
    another is never a candidate. Among the rest, the last one that starts a
    line wins: the payload comes after any log lines, and a bracket inside a
    log line ("DISMISSED: x — see [1]") can parse as JSON too. A value
    starting mid-line is only a fallback.
    """
    opener = "[" if kind == "array" else "{"
    want = list if kind == "array" else dict
    decoder = json.JSONDecoder()
    line_start: list[object] = []
    mid_line: list[object] = []
    i = 0
    while (i := text.find(opener, i)) != -1:
        try:
            value, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(value, want):
            starts_line = text[text.rfind("\n", 0, i) + 1 : i].strip() == ""
            (line_start if starts_line else mid_line).append(value)
        i = end
    if line_start:
        return line_start[-1]
    return mid_line[0] if mid_line else None


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2] not in ("array", "object"):
        print(__doc__, file=sys.stderr)
        return 2
    path, kind = argv[1], argv[2]
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"extract_json: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    value = extract(text, kind)
    if value is None:
        print(f"extract_json: no JSON {kind} in {path}", file=sys.stderr)
        return 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
