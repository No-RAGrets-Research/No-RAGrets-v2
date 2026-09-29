"""Every check in the ingestion lab. Run: ./.venv/bin/python lab/test_lab.py

No pytest on purpose. These are asserts over hand-written IR dicts, because
the metrics are pure functions and a PDF is not needed to test arithmetic.
"""
import pathlib
import copy
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lab import ir
from lab import manifest


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


def test_verify_reports_missing_extra_and_changed():
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "kept.pdf").write_bytes(b"%PDF-1.4 kept")
        (d / "surprise.pdf").write_bytes(b"%PDF-1.4 surprise")
        entries = [
            {"filename": "kept.pdf", "sha256": manifest.sha256_file(d / "kept.pdf"),
             "pages": 1, "chars_text_layer": 0, "scanned": True, "doi": None},
            {"filename": "gone.pdf", "sha256": "f" * 64,
             "pages": 1, "chars_text_layer": 0, "scanned": True, "doi": None},
        ]
        result = manifest.verify(entries=entries, directory=d)
        assert result["missing"] == ["gone.pdf"], result
        assert result["extra"] == ["surprise.pdf"], result
        assert result["changed"] == [], result
        assert result["ok"] is False


def test_verify_detects_a_changed_file():
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "a.pdf").write_bytes(b"%PDF-1.4 original")
        entries = [{"filename": "a.pdf", "sha256": "0" * 64,
                    "pages": 1, "chars_text_layer": 0, "scanned": True, "doi": None}]
        result = manifest.verify(entries=entries, directory=d)
        assert result["changed"] == ["a.pdf"], result
        assert result["ok"] is False


def test_verify_passes_on_an_exact_match():
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "a.pdf").write_bytes(b"%PDF-1.4 original")
        entries = [{"filename": "a.pdf", "sha256": manifest.sha256_file(d / "a.pdf"),
                    "pages": 1, "chars_text_layer": 0, "scanned": True, "doi": None}]
        assert manifest.verify(entries=entries, directory=d)["ok"] is True


from lab import runners


def test_split_sentences_splits_on_terminators():
    assert runners.split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_split_sentences_keeps_a_single_fragment():
    assert runners.split_sentences("no terminator here") == ["no terminator here"]


def test_chunk_blocks_starts_a_new_chunk_at_a_section_header():
    blocks = [
        {"page": 1, "kind": "section_header", "text": "Methods", "bbox": None, "order": 0},
        {"page": 1, "kind": "paragraph", "text": "Alpha.", "bbox": None, "order": 1},
        {"page": 1, "kind": "section_header", "text": "Results", "bbox": None, "order": 2},
        {"page": 1, "kind": "paragraph", "text": "Beta.", "bbox": None, "order": 3},
    ]
    chunks = runners.chunk_blocks(blocks)
    assert [c["section"] for c in chunks] == ["Methods", "Results"], chunks
    assert [c["text"] for c in chunks] == ["Alpha.", "Beta."]
    assert chunks[0]["block_ids"] == [1]


def test_chunk_blocks_respects_the_budget_and_keeps_block_ids():
    blocks = [
        {"page": 1, "kind": "paragraph", "text": "aaaa. bbbb. cccc.", "bbox": None, "order": 0},
    ]
    chunks = runners.chunk_blocks(blocks, budget=10)
    assert len(chunks) > 1, chunks
    assert all(c["block_ids"] == [0] for c in chunks), chunks
    assert all(c["chars"] == len(c["text"]) for c in chunks)


def test_chunk_blocks_skips_tables():
    blocks = [{"page": 1, "kind": "table", "text": "", "bbox": None, "order": 0}]
    assert runners.chunk_blocks(blocks) == []


def test_classify_finds_headers_and_captions():
    assert runners.classify("Methods") == "section_header"
    assert runners.classify("3. MATERIALS AND METHODS") == "section_header"
    assert runners.classify("Figure 2. Growth over time.") == "caption"
    assert runners.classify("Table 1: Yields by condition") == "caption"
    assert runners.classify("We grew the cultures for six days and measured them.") == "paragraph"


def test_group_lines_joins_a_paragraph_and_dehyphenates():
    lines = [
        {"text": "we measured the cul-", "bbox": [10, 10, 90, 20]},
        {"text": "tures every day.", "bbox": [10, 22, 90, 32]},
        {"text": "A new paragraph starts here.", "bbox": [10, 60, 90, 70]},
    ]
    blocks = runners.group_lines(lines)
    assert len(blocks) == 2, blocks
    assert blocks[0]["text"] == "we measured the cultures every day."


def test_pdfplumber_runner_smoke():
    """The one test that touches a real PDF."""
    path = pathlib.Path("fixtures/tiny.pdf")
    assert path.exists(), "run python fixtures/make_tiny_pdf.py first"
    out = runners.RUNNERS["pdfplumber"](path, "tiny", "0" * 64)
    ir.validate(out)
    assert out["pages"] == 1
    assert "Methods" in " ".join(b["text"] for b in out["blocks"])


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
