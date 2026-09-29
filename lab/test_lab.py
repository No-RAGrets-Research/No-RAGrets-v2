"""Every check in the ingestion lab. Run: python lab/test_lab.py

No pytest on purpose. These are asserts over hand-written IR dicts, because
the metrics are pure functions and a PDF is not needed to test arithmetic.
"""
import copy
import sys

from lab import ir


def good_ir():
    """A minimal two-page IR that must pass validation."""
    return {
        "paper_id": "Fixture et al 1999",
        "runner": "unit-test",
        "runner_version": "n/a",
        "pdf_sha256": "0" * 64,
        "pages": 2,
        "wall_seconds": 1.5,
        "blocks": [
            {"page": 1, "kind": "section_header", "text": "Methods", "bbox": [10, 10, 90, 20], "order": 0},
            {"page": 1, "kind": "paragraph", "text": "We did the thing.", "bbox": [10, 25, 90, 40], "order": 1},
            {"page": 2, "kind": "table", "text": "", "bbox": None, "order": 2},
        ],
        "tables": [
            {"page": 2, "rows": 3, "cols": 2, "cells": [["label", "n"], ["a", "2"], ["Total", "2"]], "caption": None},
        ],
        "chunks": [
            {"id": 0, "text": "We did the thing.", "block_ids": [1], "section": "Methods", "chars": 17},
        ],
    }


def test_validate_accepts_good_ir():
    assert ir.validate(good_ir()) is not None


def test_validate_rejects_unknown_block_kind():
    bad = good_ir()
    bad["blocks"][0]["kind"] = "heading"
    try:
        ir.validate(bad)
    except ValueError as e:
        assert "kind" in str(e)
    else:
        raise AssertionError("unknown block kind was accepted")


def test_validate_rejects_unsorted_blocks():
    bad = good_ir()
    bad["blocks"][0]["order"] = 99
    try:
        ir.validate(bad)
    except ValueError as e:
        assert "order" in str(e)
    else:
        raise AssertionError("unsorted blocks were accepted")


def test_validate_rejects_wrong_chunk_chars():
    bad = good_ir()
    bad["chunks"][0]["chars"] = 3
    try:
        ir.validate(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("chunk chars mismatch was accepted")


def test_validate_rejects_table_row_count_mismatch():
    bad = good_ir()
    bad["tables"][0]["rows"] = 9
    try:
        ir.validate(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("table row count mismatch was accepted")


def test_content_hash_ignores_timing():
    a = good_ir()
    b = copy.deepcopy(a)
    b["wall_seconds"] = 99.0
    assert ir.content_hash(a) == ir.content_hash(b)


def test_content_hash_notices_text_change():
    a = good_ir()
    b = copy.deepcopy(a)
    b["blocks"][1]["text"] = "We did something else."
    assert ir.content_hash(a) != ir.content_hash(b)


def test_chars_per_page_counts_only_text_blocks():
    counts = ir.chars_per_page(good_ir())
    assert counts[1] == len("Methods") + len("We did the thing.")
    assert counts[2] == 0


def main():
    # Collected at call time, not at import time, so later tasks can append a
    # test anywhere in this file without touching the runner.
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as e:
            failures.append(f"{t.__name__}: {type(e).__name__}: {e}")
    for f in failures:
        print("FAIL", f)
    print(f"{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
