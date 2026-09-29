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
from lab import metrics


def two_page_ir(page_one_text, page_two_text, runner_name="x"):
    blocks = []
    for page, text in ((1, page_one_text), (2, page_two_text)):
        if text:
            blocks.append({"page": page, "kind": "paragraph", "text": text,
                           "bbox": [10, 10, 90, 20], "order": len(blocks)})
    return {
        "paper_id": "p", "runner": runner_name, "runner_version": "v",
        "pdf_sha256": "0" * 64, "pages": 2, "wall_seconds": 4.0,
        "blocks": blocks, "tables": [], "chunks": [],
    }


def test_coverage_flags_a_dropped_page():
    floor = two_page_ir("x" * 1000, "y" * 1000)
    candidate = two_page_ir("x" * 1000, "y" * 20)      # page 2 is 2% of floor
    out = metrics.coverage(candidate, floor)
    assert out["dropped_pages"] == [2], out
    assert out["dropped_page_count"] == 1
    assert 0.4 < out["median_page_ratio"] < 0.6, out


def test_coverage_ignores_pages_the_floor_could_not_read():
    floor = two_page_ir("x" * 1000, "")               # floor got nothing on page 2
    candidate = two_page_ir("x" * 1000, "plenty of OCR text here")
    out = metrics.coverage(candidate, floor)
    assert out["dropped_pages"] == [], out
    assert out["pages_compared"] == 1, out


def test_agreement_is_one_for_identical_text_and_low_for_different():
    a = two_page_ir("the cultures grew quickly", "second page of prose")
    same = metrics.agreement(a, a)
    assert same["median"] == 1.0, same
    b = two_page_ir("zzzz qqqq wwww vvvv", "jjjj kkkk llll")
    assert metrics.agreement(a, b)["median"] < 0.2


def test_reading_order_penalises_a_backwards_jump():
    forwards = {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "tables": [], "chunks": [],
        "blocks": [
            {"page": 1, "kind": "paragraph", "text": "first.", "bbox": [10, 10, 90, 20], "order": 0},
            {"page": 1, "kind": "paragraph", "text": "second.", "bbox": [10, 30, 90, 40], "order": 1},
            {"page": 1, "kind": "paragraph", "text": "third.", "bbox": [10, 50, 90, 60], "order": 2},
        ],
    }
    assert metrics.reading_order(forwards)["monotonic_fraction"] == 1.0
    backwards = copy.deepcopy(forwards)
    backwards["blocks"][1]["bbox"] = [10, 500, 90, 510]   # jumps down then back up
    assert metrics.reading_order(backwards)["monotonic_fraction"] < 1.0


def test_reading_order_counts_truncated_paragraphs():
    ir_with_truncation = {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "tables": [], "chunks": [],
        "blocks": [
            {"page": 1, "kind": "paragraph", "text": "we measured the cul-", "bbox": None, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "A complete sentence.", "bbox": None, "order": 1},
        ],
    }
    out = metrics.reading_order(ir_with_truncation)
    assert out["blocks_ending_midword"] == 1, out
    assert out["monotonic_fraction"] is None, "no bboxes means no order claim"


def test_structure_proxy_counts_canonical_sections():
    sections = ["Abstract", "1. Introduction", "2. Materials and Methods",
                "3. Results", "4. Discussion", "References", "Results"]
    ir_with_sections = {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "tables": [], "chunks": [],
        "blocks": [{"page": 1, "kind": "section_header", "text": t, "bbox": None, "order": i}
                   for i, t in enumerate(sections)],
    }
    out = metrics.structure_proxy(ir_with_sections)
    assert out["counts"]["results"] == 2, out
    assert out["counts"]["methods"] == 1, out
    assert out["found_exactly_once"] == 5, out
    assert out["missing"] == [], out


def test_cost_is_seconds_per_page():
    out = metrics.cost(two_page_ir("a", "b"))
    assert out["seconds_per_page"] == 2.0, out


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


def docling_dict():
    """A hand-built DoclingDocument-shaped dict: bottom-left origin, one table."""
    return {
        "schema_name": "DoclingDocument",
        "version": "1.8.0",
        "pages": {"1": {"page_no": 1, "size": {"width": 200.0, "height": 200.0}}},
        "texts": [
            {"self_ref": "#/texts/0", "label": "section_header", "text": "Methods",
             "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 190, "r": 90, "b": 180,
                                              "coord_origin": "BOTTOMLEFT"}}]},
            {"self_ref": "#/texts/1", "label": "text", "text": "We grew cultures.",
             "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 170, "r": 90, "b": 160,
                                              "coord_origin": "BOTTOMLEFT"}}]},
            {"self_ref": "#/texts/2", "label": "caption", "text": "Table 1. Yields.",
             "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 150, "r": 90, "b": 140,
                                              "coord_origin": "BOTTOMLEFT"}}]},
        ],
        "tables": [
            {"self_ref": "#/tables/0", "label": "table",
             "captions": [{"$ref": "#/texts/2"}],
             "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 130, "r": 90, "b": 100,
                                              "coord_origin": "BOTTOMLEFT"}}],
             "data": {"num_rows": 3, "num_cols": 2,
                      "grid": [[{"text": "label"}, {"text": "n"}],
                               [{"text": "a"}, {"text": "2"}],
                               [{"text": "Total"}, {"text": "2"}]]}},
        ],
    }


def test_ir_from_docling_dict_maps_labels_and_flips_coordinates():
    out = runners.ir_from_docling_dict(
        docling_dict(), "fixture", "0" * 64, 1.0, "docling-default", "docling==2.60.0",
    )
    ir.validate(out)
    kinds = [b["kind"] for b in out["blocks"]]
    assert "section_header" in kinds and "paragraph" in kinds and "caption" in kinds, kinds
    header = next(b for b in out["blocks"] if b["kind"] == "section_header")
    # bottom-left t=190 on a 200-high page is 10 from the top
    assert abs(header["bbox"][1] - 10) < 0.01, header
    assert out["tables"][0]["caption"] == "Table 1. Yields."
    assert out["tables"][0]["cells"][2] == ["Total", "2"]


def test_ir_from_docling_dict_rebuilds_a_table_without_a_grid():
    doc = docling_dict()
    doc["tables"][0]["data"] = {
        "num_rows": 2, "num_cols": 2,
        "table_cells": [
            {"text": "x", "start_row_offset_idx": 0, "start_col_offset_idx": 0},
            {"text": "1", "start_row_offset_idx": 0, "start_col_offset_idx": 1},
            {"text": "y", "start_row_offset_idx": 1, "start_col_offset_idx": 0},
        ],
    }
    out = runners.ir_from_docling_dict(doc, "fixture", "0" * 64, 1.0, "d", "v")
    assert out["tables"][0]["cells"] == [["x", "1"], ["y", ""]]


def test_ir_from_docling_dict_omits_bbox_for_a_page_missing_its_height():
    doc = docling_dict()
    doc["texts"][1]["prov"][0]["page_no"] = 2  # page 2 is absent from "pages"
    out = runners.ir_from_docling_dict(doc, "fixture", "0" * 64, 1.0, "d", "v")
    block = next(b for b in out["blocks"] if b["text"] == "We grew cultures.")
    assert block["bbox"] is None, block


def test_tuned_converter_sets_ocr_and_accurate_tables():
    """Guards the configuration, not the conversion — building a converter is cheap,
    converting a PDF is not."""
    try:
        converter = runners.tuned_converter()
    except ImportError as e:
        raise AssertionError(f"docling not installed or backend path wrong: {e}")
    from docling.backend.docling_parse_v4_backend import DoclingParseV4DocumentBackend
    from docling.datamodel.base_models import InputFormat

    option = converter.format_to_options[InputFormat.PDF]
    pipeline = option.pipeline_options
    assert pipeline.do_ocr is True
    assert pipeline.do_table_structure is True
    assert pipeline.table_structure_options.mode.value == "accurate", pipeline.table_structure_options.mode
    assert pipeline.ocr_options.force_full_page_ocr is True, "the one real variable this runner adds"
    assert option.backend is DoclingParseV4DocumentBackend, "backend must be pinned to v4, explicitly"


def test_pdfjs_runner_smoke():
    import shutil
    if not shutil.which("node"):
        print("SKIP test_pdfjs_runner_smoke: node not installed")
        return
    out = runners.RUNNERS["pdfjs-node"](pathlib.Path("fixtures/tiny.pdf"), "tiny", "0" * 64)
    ir.validate(out)
    assert out["pages"] == 1
    assert "Methods" in " ".join(b["text"] for b in out["blocks"])
    assert out["tables"] == [], "pdf.js has no table model; empty tables is the finding, not a bug"


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
