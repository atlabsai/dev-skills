"""Tests for extract_json.py. Run: python3 -m pytest plugins/pr-review/tests"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_json as ej  # noqa: E402


def test_skips_log_lines_and_fences_before_the_array() -> None:
    text = 'DISMISSED: A — handled [elsewhere]\nMERGED: B → C\n```json\n[{"title": "x"}]\n```\nDone.'
    assert ej.extract(text, "array") == [{"title": "x"}]


def test_bracket_in_prose_that_is_not_json_is_skipped() -> None:
    assert ej.extract('see [the docs] then {"a": 1}', "object") == {"a": 1}


def test_wrong_type_or_no_json_returns_none() -> None:
    assert ej.extract('{"a": 1}', "array") is None
    assert ej.extract("No findings.", "object") is None


def test_rewrites_file_in_place_and_leaves_it_on_failure(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text('Here you go:\n{"contours": []}')
    assert ej.main(["x", str(good), "object"]) == 0
    assert good.read_text() == '{"contours": []}'

    bad = tmp_path / "bad.json"
    bad.write_text("I could not complete the analysis.")
    assert ej.main(["x", str(bad), "object"]) == 1
    assert bad.read_text() == "I could not complete the analysis."


def test_array_inside_a_log_line_does_not_win() -> None:
    text = 'DISMISSED: A — already handled, see [] and [1]\n[{"title": "real"}]'
    assert ej.extract(text, "array") == [{"title": "real"}]


def test_nested_arrays_inside_the_payload_are_not_picked_separately() -> None:
    text = '[\n  {"file_refs": [\n    {"line": 1}\n  ]}\n]'
    assert ej.extract(text, "array") == [{"file_refs": [{"line": 1}]}]


def test_pretty_printed_object_is_not_replaced_by_a_nested_one() -> None:
    text = 'Analysis done.\n{\n  "contours": [\n    {\n      "name": "Checkout"\n    }\n  ]\n}'
    assert ej.extract(text, "object") == {"contours": [{"name": "Checkout"}]}
