# Ingestion Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a label-free benchmark that measures how much of a scientific PDF each of four extractors recovers, so any later ingestion change is attributable.

**Architecture:** Four runners each convert a PDF into one shared JSON intermediate representation (IR). A metrics module scores IR against IR — never against a gold standard, because none exists. A report command aggregates per-runner scores into a committed markdown table. No model calls anywhere, so the whole harness is free and deterministic.

**Tech Stack:** Python 3.11, `docling==2.60.0`, `pdfplumber`, Node + `pdfjs-dist` for one runner. Standard library for everything else — no pytest, no pandas, no config framework.

**Spec:** `docs/superpowers/specs/2026-09-28-ingestion-lab-design.md`

## Global Constraints

- **Zero cost.** No model calls in the harness, no paid services, no hosting. A free tier that can bill is disqualified.
- **No ground truth.** Every metric is mechanical and label-free. Do not add an LLM judge; v1's six judges scored the same 94 relations 66%–100%.
- **No composite score.** Never aggregate metrics into one number. v1's unreproducible "96.45%" came from exactly that move with no recorded formula.
- **Docling pins to `2.60.0`**, and `backend=DoclingParseDocumentBackend` is passed explicitly regardless of version. 2.123.0+ is affected by open issues #4174 (~4x slower) and #4357 (drops scanned OCR text).
- **pdfplumber is the floor runner, never PyMuPDF.** PyMuPDF is AGPL and this repo is public.
- **The corpus never enters the repo.** `corpus/` is gitignored and located by `$NORAGRETS_CORPUS`. `results/*.jsonl` is gitignored too — it contains full paper text. Only `corpus.manifest.json` and `results/REPORT.md` are committed.
- **Python 3.11.**
- Chunking is held constant across runners in this plan. Extraction is the only variable.

## File Structure

The spec's layout sketch is refined here: `ir.py`, `manifest.py`, and `report.py` are split out because three or more modules import each, and the IR is the interface the rest of No RAGrets v2 will consume.

| File | Responsibility |
|---|---|
| `lab/ir.py` | IR field list, `validate()`, `content_hash()`, page-text helper. The published interface. |
| `lab/manifest.py` | Corpus location, sha256, manifest build and verify. |
| `lab/runners.py` | The four runners, the shared line/paragraph grouping, the chunker. |
| `lab/metrics.py` | The eight metric families. Pure functions over IR dicts. |
| `lab/report.py` | Aggregate results into `results/REPORT.md`. |
| `lab/cli.py` | `manifest` / `run` / `compare` subcommands. |
| `lab/__main__.py` | One line so `python -m lab` works. |
| `lab/pdfjs_runner.mjs` | Node side of the pdfjs runner. Emits per-page lines as JSON on stdout. |
| `lab/test_lab.py` | Every check in the project. Asserts and a `__main__`. |
| `fixtures/make_tiny_pdf.py` | Generates the committed one-page fixture PDF. |
| `requirements.txt`, `package.json`, `.gitignore` | Environment. |

---

### Task 1: Scaffold and the IR module

**Files:**
- Create: `lab/__init__.py`, `lab/__main__.py`, `lab/ir.py`, `lab/test_lab.py`, `requirements.txt`, `.gitignore`
- Test: `lab/test_lab.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lab.ir.BLOCK_KINDS: set[str]`, `lab.ir.IR_FIELDS: tuple[str, ...]`, `lab.ir.validate(ir: dict) -> dict` (raises `ValueError`), `lab.ir.content_hash(ir: dict) -> str`, `lab.ir.chars_per_page(ir: dict) -> dict[int, int]`, `lab.ir.page_text(ir: dict, page: int) -> str`.

- [ ] **Step 1: Create the environment files**

`requirements.txt`:

```
docling==2.60.0
docling-core==2.50.0
pdfplumber==0.11.4
```

`.gitignore` (append to the existing one):

```
corpus/
results/*.jsonl
node_modules/
__pycache__/
*.pyc
.venv/
```

`lab/__init__.py`: empty file.

`lab/__main__.py`:

```python
from lab.cli import main

main()
```

Note: `lab/cli.py` does not exist until Task 2, so `python -m lab` fails until then. That is expected.

- [ ] **Step 2: Write the failing tests**

Create `lab/test_lab.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd ~/Desktop/Active\ Projects/No-RAGrets-v2 && python lab/test_lab.py`
Expected: `ModuleNotFoundError: No module named 'lab.ir'` — the import at the top of the file fails before any test runs.

- [ ] **Step 4: Write `lab/ir.py`**

```python
"""The IR every runner emits and every metric consumes.

This is the interface the UI, RAG and anomaly-detection parts of No RAGrets v2
will depend on, so a change here is a breaking change for the whole project.

Shape:
    {paper_id, runner, runner_version, pdf_sha256, pages, wall_seconds,
     blocks: [{page, kind, text, bbox|null, order}],
     tables: [{page, rows, cols, cells, caption|null}],
     chunks: [{id, text, block_ids, section, chars}]}

`bbox` is [x0, top, x1, bottom] in top-down page coordinates, or null for
runners that cannot supply it. `order` is the block's index in reading order
and is what `chunk.block_ids` refers to.
"""
import hashlib
import json

BLOCK_KINDS = {"paragraph", "section_header", "table", "caption", "other"}

IR_FIELDS = (
    "paper_id", "runner", "runner_version", "pdf_sha256",
    "pages", "wall_seconds", "blocks", "tables", "chunks",
)

# Everything except timing, so two runs of one runner over one PDF compare
# byte for byte.
HASHED_FIELDS = tuple(f for f in IR_FIELDS if f != "wall_seconds")

TEXT_KINDS = {"paragraph", "section_header", "caption", "other"}


def validate(ir):
    """Raise ValueError on anything a metric could not read. Returns ir."""
    for field in IR_FIELDS:
        if field not in ir:
            raise ValueError(f"missing field: {field}")
    if not isinstance(ir["pages"], int) or ir["pages"] < 1:
        raise ValueError(f"pages must be a positive int, got {ir['pages']!r}")

    for i, b in enumerate(ir["blocks"]):
        if b.get("kind") not in BLOCK_KINDS:
            raise ValueError(f"block {i}: unknown kind {b.get('kind')!r}")
        if not isinstance(b.get("text"), str):
            raise ValueError(f"block {i}: text must be a str")
        if not isinstance(b.get("page"), int) or b["page"] < 1:
            raise ValueError(f"block {i}: page must be a positive int")
        if not isinstance(b.get("order"), int):
            raise ValueError(f"block {i}: order must be an int")
        bbox = b.get("bbox", "missing")
        if bbox == "missing":
            raise ValueError(f"block {i}: bbox key required (use null if unavailable)")
        if bbox is not None:
            if len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
                raise ValueError(f"block {i}: bbox must be null or four numbers")

    orders = [b["order"] for b in ir["blocks"]]
    if orders != sorted(orders):
        raise ValueError("blocks must be sorted by order")

    for i, t in enumerate(ir["tables"]):
        for key in ("page", "rows", "cols"):
            if not isinstance(t.get(key), int):
                raise ValueError(f"table {i}: {key} must be an int")
        cells = t.get("cells")
        if not isinstance(cells, list) or len(cells) != t["rows"]:
            raise ValueError(f"table {i}: cells has {len(cells or [])} rows, rows says {t['rows']}")
        for r, row in enumerate(cells):
            if len(row) != t["cols"]:
                raise ValueError(f"table {i} row {r}: {len(row)} cells, cols says {t['cols']}")

    known_orders = set(orders)
    for i, c in enumerate(ir["chunks"]):
        if not isinstance(c.get("text"), str):
            raise ValueError(f"chunk {i}: text must be a str")
        if c.get("chars") != len(c["text"]):
            raise ValueError(f"chunk {i}: chars={c.get('chars')} but text is {len(c['text'])} long")
        for bid in c.get("block_ids", []):
            if bid not in known_orders:
                raise ValueError(f"chunk {i}: block_id {bid} matches no block order")
    return ir


def content_hash(ir):
    """Stable sha256 over everything but timing."""
    payload = {k: ir[k] for k in HASHED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def chars_per_page(ir):
    """Text characters recovered per page. Tables carry no text of their own."""
    counts = {p: 0 for p in range(1, ir["pages"] + 1)}
    for b in ir["blocks"]:
        if b["kind"] in TEXT_KINDS:
            counts[b["page"]] = counts.get(b["page"], 0) + len(b["text"])
    return counts


def page_text(ir, page):
    return " ".join(
        b["text"] for b in ir["blocks"]
        if b["page"] == page and b["kind"] in TEXT_KINDS
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `8/8 passed`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add lab/__init__.py lab/__main__.py lab/ir.py lab/test_lab.py requirements.txt .gitignore
git commit -m "feat: IR schema, validation and content hash"
```

---

### Task 2: Corpus manifest and the CLI skeleton

**Files:**
- Create: `lab/manifest.py`, `lab/cli.py`
- Modify: `lab/test_lab.py` (add manifest tests)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `lab.manifest.corpus_dir() -> pathlib.Path`, `lab.manifest.sha256_file(path) -> str`, `lab.manifest.describe(path) -> dict`, `lab.manifest.build() -> list[dict]`, `lab.manifest.load() -> list[dict]`, `lab.manifest.verify() -> dict` with keys `missing`, `extra`, `changed`, `ok`. Manifest entry keys: `filename`, `sha256`, `pages`, `chars_text_layer`, `scanned`, `doi`.
- Produces: `lab.cli.main() -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `lab/test_lab.py`:

```python
import json as _json
import pathlib
import tempfile

from lab import manifest


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python lab/test_lab.py`
Expected: `ModuleNotFoundError: No module named 'lab.manifest'`.

- [ ] **Step 3: Write `lab/manifest.py`**

```python
"""The corpus lives outside the repo. The manifest is how a run proves it is
looking at the same papers as the last run.

This exists because of a real failure in v1: data/docling_json/ holds 49 JSON
files for 47 PDFs, because its cache was a filename-stem existence check with
no content hash and no version awareness.
"""
import hashlib
import json
import os
import pathlib

MANIFEST_PATH = pathlib.Path("corpus.manifest.json")

# A born-digital page carries far more than this. Below it, the page is either
# a scan with no OCR layer or a scan whose OCR layer is broken.
# Known ceiling: a genuinely sparse page (a full-page figure) reads as scanned.
SCANNED_CHARS_PER_PAGE = 200


def corpus_dir():
    raw = os.environ.get("NORAGRETS_CORPUS")
    if not raw:
        raise SystemExit("set NORAGRETS_CORPUS to the directory holding the PDFs")
    path = pathlib.Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit(f"NORAGRETS_CORPUS is not a directory: {path}")
    return path


def pdf_paths(directory=None):
    directory = directory or corpus_dir()
    return sorted(p for p in directory.iterdir() if p.suffix.lower() == ".pdf")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(path):
    """One manifest entry. Opens the PDF once with pdfplumber for page count
    and text-layer size."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        chars = sum(len(page.extract_text() or "") for page in pdf.pages)
    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "pages": pages,
        "chars_text_layer": chars,
        "scanned": pages > 0 and (chars / pages) < SCANNED_CHARS_PER_PAGE,
        "doi": None,
    }


def build(directory=None):
    entries = [describe(p) for p in pdf_paths(directory)]
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
    return entries


def load():
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"{MANIFEST_PATH} not found — run: python -m lab manifest build")
    return json.loads(MANIFEST_PATH.read_text())


def verify(entries=None, directory=None):
    """Compare the manifest against what is actually on disk."""
    entries = load() if entries is None else entries
    directory = directory or corpus_dir()
    on_disk = {p.name: p for p in pdf_paths(directory)}
    expected = {e["filename"]: e for e in entries}

    missing = sorted(set(expected) - set(on_disk))
    extra = sorted(set(on_disk) - set(expected))
    changed = sorted(
        name for name in set(expected) & set(on_disk)
        if sha256_file(on_disk[name]) != expected[name]["sha256"]
    )
    return {
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "ok": not (missing or extra or changed),
    }


def entry_for(filename, entries=None):
    entries = load() if entries is None else entries
    for e in entries:
        if e["filename"] == filename:
            return e
    raise SystemExit(f"{filename} is not in {MANIFEST_PATH} — rebuild the manifest")
```

- [ ] **Step 4: Write `lab/cli.py` with the manifest subcommand only**

Later tasks add `run` and `compare`. The dispatch table is written now so those tasks only append.

```python
"""python -m lab manifest build|verify | run <runner> | compare"""
import argparse
import json
import pathlib
import sys

RESULTS_DIR = pathlib.Path("results")


def cmd_manifest(args):
    from lab import manifest

    if args.action == "build":
        entries = manifest.build()
        scanned = sum(1 for e in entries if e["scanned"])
        print(f"wrote {manifest.MANIFEST_PATH} — {len(entries)} papers, {scanned} look scanned")
        return 0

    result = manifest.verify()
    for label in ("missing", "extra", "changed"):
        for name in result[label]:
            print(f"{label.upper():8} {name}")
    print("manifest ok" if result["ok"] else "manifest does NOT match the corpus")
    return 0 if result["ok"] else 1


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m lab")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("manifest", help="build or verify the corpus manifest")
    m.add_argument("action", choices=["build", "verify"])
    m.set_defaults(func=cmd_manifest)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `11/11 passed`.

- [ ] **Step 6: Build the real manifest and sanity-check it**

```bash
export NORAGRETS_CORPUS=~/Desktop/Active\ Projects/No-RAGrets-Master/data/papers
python -m lab manifest build
python -m lab manifest verify
```

Expected: 47 papers, `manifest ok`. Record the scanned count in the commit message — it is the number that justifies caring about OCR at all.

- [ ] **Step 7: Commit**

```bash
git add lab/manifest.py lab/cli.py lab/test_lab.py corpus.manifest.json
git commit -m "feat: corpus manifest with sha256 verification"
```

---

### Task 3: The chunker, the pdfplumber floor runner, and `run`

This is the largest task because the floor runner defines the helpers every other runner reuses: line grouping, paragraph grouping, header/caption classification, and the chunker. Splitting it would mean writing a runner with no way to execute it.

**Files:**
- Create: `lab/runners.py`, `fixtures/make_tiny_pdf.py`, `fixtures/tiny.pdf`
- Modify: `lab/cli.py` (add the `run` subcommand), `lab/test_lab.py` (chunker + smoke tests)

**Interfaces:**
- Consumes: `lab.ir.validate`, `lab.manifest.entry_for`, `lab.manifest.corpus_dir`.
- Produces:
  - `lab.runners.RUNNERS: dict[str, callable]` — name to `fn(pdf_path: pathlib.Path, paper_id: str, sha256: str) -> dict` (an IR).
  - `lab.runners.split_sentences(text: str) -> list[str]`
  - `lab.runners.chunk_blocks(blocks: list[dict], budget: int = 1200) -> list[dict]`
  - `lab.runners.group_lines(lines: list[dict]) -> list[dict]` — lines in, paragraph-ish blocks out. A line is `{"text": str, "bbox": [x0, top, x1, bottom]}`.
  - `lab.runners.classify(text: str) -> str` — one of `BLOCK_KINDS`.
  - `lab.runners.finish(paper_id, runner_name, runner_version, sha256, pages, wall_seconds, blocks, tables) -> dict` — numbers the blocks, chunks them, validates, returns the IR. Every runner ends with this call, which is what holds chunking constant.

- [ ] **Step 1: Write the failing tests**

Append to `lab/test_lab.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python lab/test_lab.py`
Expected: `ModuleNotFoundError: No module named 'lab.runners'`.

- [ ] **Step 3: Create the fixture PDF generator and run it**

`fixtures/make_tiny_pdf.py` — writes a valid one-page PDF with no dependencies, so the fixture is reproducible rather than a mystery binary:

```python
"""Generate fixtures/tiny.pdf: one page, four lines, one of them a 'Total' row.

Hand-rolled so the fixture needs no PDF library and can be regenerated byte for
byte. Run: python fixtures/make_tiny_pdf.py
"""
import pathlib

stream = (
    b"BT /F1 12 Tf 20 170 Td (Methods) Tj "
    b"0 -20 Td (alpha 2) Tj "
    b"0 -20 Td (beta 3) Tj "
    b"0 -20 Td (Total 5) Tj ET"
)

objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
    b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
]

out = bytearray(b"%PDF-1.4\n")
offsets = []
for number, body in enumerate(objects, start=1):
    offsets.append(len(out))
    out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

startxref = len(out)
out += b"xref\n0 %d\n" % (len(objects) + 1)
out += b"0000000000 65535 f \n"
for offset in offsets:
    out += b"%010d 00000 n \n" % offset
out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
    len(objects) + 1, startxref,
)

path = pathlib.Path(__file__).parent / "tiny.pdf"
path.write_bytes(bytes(out))
print(f"wrote {path} ({len(out)} bytes)")
```

Run: `python fixtures/make_tiny_pdf.py`
Then confirm the PDF is readable before trusting it as a fixture:
Run: `python -c "import pdfplumber; print(repr(pdfplumber.open('fixtures/tiny.pdf').pages[0].extract_text()))"`
Expected: text containing `Methods`, `alpha 2`, `beta 3`, `Total 5`.

- [ ] **Step 4: Write `lab/runners.py`**

```python
"""The four runners, and the helpers they share.

Every runner ends by calling finish(), which applies the one chunker. That is
what holds chunking constant so extraction is the only variable.
"""
import json
import pathlib
import re
import statistics
import subprocess
import time

from lab import ir

RUNNERS = {}


def runner(name):
    def register(fn):
        RUNNERS[name] = fn
        return fn
    return register


# ---------------------------------------------------------------- classification

CANONICAL_SECTIONS = (
    "abstract", "introduction", "background", "methods", "materials and methods",
    "method", "results", "results and discussion", "discussion", "conclusion",
    "conclusions", "references", "acknowledgements", "acknowledgments",
)

CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|table|scheme|plate)\s*\d+", re.I)
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(\.\d+)*)[.)]?\s+(?P<rest>[A-Za-z].*)$")


def classify(text):
    """Header / caption / paragraph from the text alone.

    Known ceiling: no font-size or boldness signal, because two of the four
    runners do not expose it. An all-caps figure caption could read as a header.
    Upgrade path is passing per-line font size through the line dicts.
    """
    stripped = text.strip()
    if not stripped:
        return "other"
    if CAPTION_RE.match(stripped):
        return "caption"

    candidate = stripped
    numbered = NUMBERED_HEADING_RE.match(stripped)
    if numbered:
        candidate = numbered.group("rest")

    bare = candidate.rstrip(":.").strip()
    if bare.lower() in CANONICAL_SECTIONS:
        return "section_header"
    words = bare.split()
    if numbered and len(words) <= 8 and not bare.endswith("."):
        return "section_header"
    if len(words) <= 6 and bare.isupper() and len(bare) > 2:
        return "section_header"
    return "paragraph"


# ------------------------------------------------------------- line -> paragraph

def group_lines(lines):
    """Join lines into paragraph-ish blocks on vertical gaps.

    Runners that emit lines (pdfplumber, pdfjs) go through this so their block
    granularity matches Docling's. Without it, the reading-order metric would
    measure block size rather than extraction quality.
    """
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return []

    heights = [l["bbox"][3] - l["bbox"][1] for l in lines if l["bbox"]]
    typical = statistics.median(heights) if heights else 10.0
    gap_limit = 1.6 * typical

    groups = [[lines[0]]]
    for previous, current in zip(lines, lines[1:]):
        gap = current["bbox"][1] - previous["bbox"][3] if (previous["bbox"] and current["bbox"]) else 0
        starts_new = (
            gap > gap_limit
            or classify(current["text"]) != "paragraph"
            or classify(previous["text"]) != "paragraph"
        )
        if starts_new:
            groups.append([current])
        else:
            groups[-1].append(current)

    blocks = []
    for group in groups:
        text = _join_lines([l["text"] for l in group])
        boxes = [l["bbox"] for l in group if l["bbox"]]
        bbox = None
        if boxes:
            bbox = [
                min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes),
            ]
        blocks.append({"kind": classify(text), "text": text, "bbox": bbox})
    return blocks


def _join_lines(texts):
    out = ""
    for text in texts:
        piece = text.strip()
        if not out:
            out = piece
        elif out.endswith("-"):
            out = out[:-1] + piece      # de-hyphenate a wrapped word
        else:
            out = out + " " + piece
    return out


# -------------------------------------------------------------------- chunking

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
CHUNK_BUDGET = 1200


def split_sentences(text):
    """Regex sentence splitting.

    Known ceiling: splits on "et al. 1984" and other abbreviations. Upgrade path
    is swapping this one function for spaCy if chunk-health numbers turn out to
    be dominated by split noise rather than extraction quality.
    """
    return [s.strip() for s in SENTENCE_BOUNDARY.split(text) if s.strip()]


CHUNKABLE = {"paragraph", "caption", "other"}


def chunk_blocks(blocks, budget=CHUNK_BUDGET):
    """Split on section headers, then pack to a character budget on sentence
    boundaries."""
    chunks = []
    section = "(front matter)"
    buffer = []
    block_ids = []

    def flush():
        nonlocal buffer, block_ids
        text = " ".join(buffer).strip()
        if text:
            chunks.append({
                "id": len(chunks), "text": text, "block_ids": list(block_ids),
                "section": section, "chars": len(text),
            })
        buffer = []
        block_ids = []

    for block in blocks:
        if block["kind"] == "section_header":
            flush()
            section = block["text"].strip() or section
            continue
        if block["kind"] not in CHUNKABLE:
            continue
        for sentence in split_sentences(block["text"]):
            used = len(" ".join(buffer))
            if buffer and used + len(sentence) + 1 > budget:
                flush()
            buffer.append(sentence)
            if block["order"] not in block_ids:
                block_ids.append(block["order"])
    flush()
    return chunks


# ---------------------------------------------------------------------- finish

def finish(paper_id, runner_name, runner_version, sha256, pages, wall_seconds, blocks, tables):
    """Number the blocks, chunk them, validate, return the IR."""
    for index, block in enumerate(blocks):
        block["order"] = index
        block.setdefault("bbox", None)
    return ir.validate({
        "paper_id": paper_id,
        "runner": runner_name,
        "runner_version": runner_version,
        "pdf_sha256": sha256,
        "pages": pages,
        "wall_seconds": round(wall_seconds, 3),
        "blocks": blocks,
        "tables": tables,
        "chunks": chunk_blocks(blocks),
    })


# ------------------------------------------------------------ pdfplumber floor

def _pdfplumber_lines(page, tolerance=2.0):
    rows = {}
    for word in page.extract_words():
        rows.setdefault(round(word["top"] / tolerance), []).append(word)
    lines = []
    for key in sorted(rows):
        words = sorted(rows[key], key=lambda w: w["x0"])
        lines.append({
            "text": " ".join(w["text"] for w in words),
            "bbox": [
                min(w["x0"] for w in words), min(w["top"] for w in words),
                max(w["x1"] for w in words), max(w["bottom"] for w in words),
            ],
        })
    return lines


@runner("pdfplumber")
def run_pdfplumber(pdf_path, paper_id, sha256):
    """The floor. MIT-licensed, no OCR, no ML — whatever a plain text layer gives."""
    import pdfplumber

    started = time.time()
    blocks = []
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            for raw in page.extract_tables():
                rows = [[(cell or "").strip() for cell in row] for row in raw]
                cols = max((len(row) for row in rows), default=0)
                rows = [row + [""] * (cols - len(row)) for row in rows]
                if not rows or not cols:
                    continue
                tables.append({
                    "page": number, "rows": len(rows), "cols": cols,
                    "cells": rows, "caption": None,
                })
                blocks.append({"page": number, "kind": "table", "text": "", "bbox": None})
            for block in group_lines(_pdfplumber_lines(page)):
                block["page"] = number
                blocks.append(block)

    return finish(
        paper_id, "pdfplumber", _version("pdfplumber"), sha256,
        page_count, time.time() - started, blocks, tables,
    )


def _version(package):
    from importlib.metadata import version
    try:
        return f"{package}=={version(package)}"
    except Exception:
        return f"{package}==unknown"
```

- [ ] **Step 5: Add the `run` subcommand to `lab/cli.py`**

Insert `cmd_run` above `build_parser`, and register it inside `build_parser` before the `return`:

```python
def cmd_run(args):
    from lab import ir, manifest, runners

    if args.runner not in runners.RUNNERS:
        raise SystemExit(f"unknown runner {args.runner!r}; have: {', '.join(sorted(runners.RUNNERS))}")

    check = manifest.verify()
    if not check["ok"]:
        raise SystemExit(
            "corpus does not match corpus.manifest.json "
            f"(missing={check['missing']}, extra={check['extra']}, changed={check['changed']}). "
            "Fix the corpus or rebuild the manifest; a run over a drifted corpus is not comparable."
        )

    entries = manifest.load()
    if args.limit:
        entries = entries[: args.limit]

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{args.runner}.jsonl"
    done = {}
    if out_path.exists() and not args.force:
        for line in out_path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["paper_id"]] = record

    directory = manifest.corpus_dir()
    written = 0
    with out_path.open("w") as fh:
        for entry in entries:
            paper_id = pathlib.Path(entry["filename"]).stem
            cached = done.get(paper_id)
            if cached and cached["pdf_sha256"] == entry["sha256"] and not args.force:
                fh.write(json.dumps(cached) + "\n")
                continue
            try:
                result = runners.RUNNERS[args.runner](
                    directory / entry["filename"], paper_id, entry["sha256"],
                )
            except Exception as e:
                print(f"FAILED  {paper_id}: {type(e).__name__}: {e}")
                continue
            fh.write(json.dumps(result) + "\n")
            written += 1
            print(f"{args.runner:16} {paper_id:45} {result['wall_seconds']:7.1f}s "
                  f"{len(result['blocks']):5d} blocks {len(result['tables']):3d} tables")

    print(f"wrote {written} fresh results to {out_path}")
    return 0
```

Registration, inside `build_parser`:

```python
    r = sub.add_parser("run", help="run one runner over the corpus")
    r.add_argument("runner")
    r.add_argument("--limit", type=int, default=0, help="only the first N papers")
    r.add_argument("--force", action="store_true", help="ignore cached results")
    r.set_defaults(func=cmd_run)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `19/19 passed`.

- [ ] **Step 7: Run the floor runner over three real papers**

Run: `python -m lab run pdfplumber --limit 3`
Expected: three lines of per-paper output, non-zero block counts, and `results/pdfplumber.jsonl` created. If any paper produces zero blocks, stop and investigate before continuing — a floor runner that finds nothing makes the coverage metric meaningless.

- [ ] **Step 8: Commit**

```bash
git add lab/runners.py lab/cli.py lab/test_lab.py fixtures/make_tiny_pdf.py fixtures/tiny.pdf
git commit -m "feat: chunker, pdfplumber floor runner, and run command"
```

---

### Task 4: The docling-default baseline runner

**Files:**
- Modify: `lab/runners.py`, `lab/test_lab.py`

**Interfaces:**
- Consumes: `lab.runners.finish`, `lab.runners.classify`.
- Produces: `lab.runners.ir_from_docling_dict(doc: dict, paper_id, sha256, wall_seconds, runner_name, runner_version) -> dict`, `RUNNERS["docling-default"]`, and `lab.runners.import_docling_json(json_path, paper_id, sha256) -> dict` used by the baseline import.

- [ ] **Step 1: Write the failing test**

Append to `lab/test_lab.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python lab/test_lab.py`
Expected: `AttributeError: module 'lab.runners' has no attribute 'ir_from_docling_dict'`.

- [ ] **Step 3: Append the Docling code to `lab/runners.py`**

```python
# ------------------------------------------------------------------- docling

# DoclingDocument labels -> our block kinds.
DOCLING_LABEL_KIND = {
    "title": "section_header",
    "section_header": "section_header",
    "caption": "caption",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "paragraph",
    "footnote": "other",
    "page_header": "other",
    "page_footer": "other",
    "formula": "other",
    "code": "other",
    "reference": "paragraph",
}


def _page_heights(doc):
    pages = doc.get("pages") or {}
    if isinstance(pages, dict):
        items = pages.values()
    else:
        items = pages
    heights = {}
    for page in items:
        number = page.get("page_no")
        size = page.get("size") or {}
        if number is not None:
            heights[int(number)] = float(size.get("height") or 0.0)
    return heights


def _docling_prov(item, heights):
    """Return (page, bbox) with bbox in top-down coordinates, or (None, None).

    Docling reports bottom-left origin by default: t is the distance from the
    bottom, so it must be flipped or every reading-order number is inverted.
    """
    prov = (item.get("prov") or [None])[0]
    if not prov:
        return None, None
    page = prov.get("page_no")
    box = prov.get("bbox") or {}
    if not box or page is None:
        return page, None
    left, right = box.get("l"), box.get("r")
    top, bottom = box.get("t"), box.get("b")
    if None in (left, right, top, bottom):
        return page, None
    if (box.get("coord_origin") or "BOTTOMLEFT").upper() == "BOTTOMLEFT":
        height = heights.get(int(page), 0.0)
        top, bottom = height - top, height - bottom
    if top > bottom:
        top, bottom = bottom, top
    return page, [float(left), float(top), float(right), float(bottom)]


def _docling_cells(data):
    grid = data.get("grid")
    if grid:
        return [[(cell or {}).get("text", "") or "" for cell in row] for row in grid]

    cells = data.get("table_cells") or []
    rows = data.get("num_rows") or max((c.get("end_row_offset_idx", 0) for c in cells), default=0)
    cols = data.get("num_cols") or max((c.get("end_col_offset_idx", 0) for c in cells), default=0)
    grid = [[""] * cols for _ in range(rows)]
    for cell in cells:
        r = cell.get("start_row_offset_idx", 0)
        c = cell.get("start_col_offset_idx", 0)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = cell.get("text", "") or ""
    return grid


def ir_from_docling_dict(doc, paper_id, sha256, wall_seconds, runner_name, runner_version):
    heights = _page_heights(doc)
    by_ref = {t.get("self_ref"): (t.get("text") or "") for t in doc.get("texts") or []}

    items = []
    for text_item in doc.get("texts") or []:
        page, bbox = _docling_prov(text_item, heights)
        body = text_item.get("text") or ""
        if not body.strip() or page is None:
            continue
        kind = DOCLING_LABEL_KIND.get(text_item.get("label"), "other")
        if kind == "paragraph":
            # Docling labels many headers plainly "text"; re-check by content.
            kind = classify(body)
        items.append((page, bbox, {"page": int(page), "kind": kind, "text": body, "bbox": bbox}))

    tables = []
    for table_item in doc.get("tables") or []:
        page, bbox = _docling_prov(table_item, heights)
        if page is None:
            continue
        cells = _docling_cells(table_item.get("data") or {})
        cols = max((len(row) for row in cells), default=0)
        cells = [row + [""] * (cols - len(row)) for row in cells]
        caption_refs = table_item.get("captions") or []
        caption = next((by_ref.get(r.get("$ref")) for r in caption_refs if r.get("$ref") in by_ref), None)
        tables.append({
            "page": int(page), "rows": len(cells), "cols": cols,
            "cells": cells, "caption": caption,
        })
        items.append((page, bbox, {"page": int(page), "kind": "table", "text": "", "bbox": bbox}))

    def sort_key(entry):
        page, bbox, _ = entry
        top = bbox[1] if bbox else 0.0
        left = bbox[0] if bbox else 0.0
        return (int(page), round(top, 1), round(left, 1))

    blocks = [block for _, _, block in sorted(items, key=sort_key)]
    pages = max(heights) if heights else max((b["page"] for b in blocks), default=1)
    return finish(paper_id, runner_name, runner_version, sha256,
                  int(pages), wall_seconds, blocks, tables)


def import_docling_json(json_path, paper_id, sha256):
    """Import a DoclingDocument JSON produced earlier by a bare DocumentConverter.

    This is how the baseline costs zero compute: the 47 files in
    No-RAGrets-Master/data/docling_json/ came from
    pipeline/kg_gen_pipeline/core/pdf_converter.py:44 at docling 2.60.0.
    wall_seconds is 0.0 because the conversion is not being timed here.
    """
    doc = json.loads(pathlib.Path(json_path).read_text())
    return ir_from_docling_dict(doc, paper_id, sha256, 0.0,
                                "docling-default", "docling==2.60.0 (imported)")


@runner("docling-default")
def run_docling_default(pdf_path, paper_id, sha256):
    """Exactly what v1 ran: bare DocumentConverter(), every option default."""
    from docling.document_converter import DocumentConverter

    started = time.time()
    result = DocumentConverter().convert(str(pdf_path))
    doc = result.document.export_to_dict()
    return ir_from_docling_dict(doc, paper_id, sha256, time.time() - started,
                                "docling-default", _version("docling"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `21/21 passed`.

- [ ] **Step 5: Verify the runner against one real PDF**

Run: `python -m lab run docling-default --limit 1`
Expected: one result line. Note the wall seconds — at 2.60.0 on CPU this is tens of seconds per paper, which is why the baseline is normally imported rather than re-run.

- [ ] **Step 6: Commit**

```bash
git add lab/runners.py lab/test_lab.py
git commit -m "feat: docling-default baseline runner and DoclingDocument import"
```

---

### Task 5: The docling-tuned candidate runner

**Files:**
- Modify: `lab/runners.py`, `lab/test_lab.py`

**Interfaces:**
- Consumes: `lab.runners.ir_from_docling_dict`, `lab.runners._version`.
- Produces: `RUNNERS["docling-tuned"]`, `lab.runners.tuned_converter() -> DocumentConverter`.

- [ ] **Step 1: Confirm the backend import path before writing code**

The explicit-backend requirement is a global constraint, and the import path moved across docling versions. Find the one that exists:

```bash
python - <<'PY'
for path, name in [
    ("docling.backend.docling_parse_backend", "DoclingParseDocumentBackend"),
    ("docling.backend.docling_parse_v2_backend", "DoclingParseV2DocumentBackend"),
]:
    try:
        module = __import__(path, fromlist=[name])
        print("OK  ", path, name, getattr(module, name))
    except Exception as e:
        print("MISS", path, name, type(e).__name__, e)
PY
```

Use whichever prints `OK`. If both do, use the non-v2 `DoclingParseDocumentBackend` — that is the one the two open issues name. If neither does, stop and report; do not silently fall back to the default backend, because that is the exact thing the constraint exists to prevent.

- [ ] **Step 2: Write the failing test**

Append to `lab/test_lab.py`:

```python
def test_tuned_converter_sets_ocr_and_accurate_tables():
    """Guards the configuration, not the conversion — building a converter is cheap,
    converting a PDF is not."""
    try:
        converter = runners.tuned_converter()
    except ImportError as e:
        raise AssertionError(f"docling not installed or backend path wrong: {e}")
    from docling.datamodel.base_models import InputFormat

    option = converter.format_to_options[InputFormat.PDF]
    pipeline = option.pipeline_options
    assert pipeline.do_ocr is True
    assert pipeline.do_table_structure is True
    assert pipeline.table_structure_options.mode.value == "accurate", pipeline.table_structure_options.mode
    assert option.backend is not None, "backend must be explicit, never the default"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python lab/test_lab.py`
Expected: `AttributeError: module 'lab.runners' has no attribute 'tuned_converter'`.

- [ ] **Step 4: Append the tuned runner to `lab/runners.py`**

Replace `DoclingParseDocumentBackend` below with whatever Step 1 confirmed.

```python
def tuned_converter():
    """OCR on, accurate table structure, backend pinned explicitly.

    The explicit backend is not optional. Docling 2.123.0 made threaded
    docling-parse the default (PR #3764) and that default is what drops most of
    a scanned PDF's OCR text layer (issue #4357) and runs ~4x slower on CPU
    (issue #4174). Both were still open on 2026-09-28. Passing the backend here
    means this runner behaves the same if the pin ever moves.
    """
    from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.generate_page_images = False   # nothing here looks at images

    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=options,
            backend=DoclingParseDocumentBackend,
        )
    })


@runner("docling-tuned")
def run_docling_tuned(pdf_path, paper_id, sha256):
    started = time.time()
    result = tuned_converter().convert(str(pdf_path))
    doc = result.document.export_to_dict()
    return ir_from_docling_dict(doc, paper_id, sha256, time.time() - started,
                                "docling-tuned", _version("docling"))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `22/22 passed`.

- [ ] **Step 6: Run it over one scanned paper**

Pick a paper the manifest flagged `scanned: true`:

```bash
python - <<'PY'
import json
entries = json.load(open("corpus.manifest.json"))
print([e["filename"] for e in entries if e["scanned"]][:5])
PY
```

Then run the two docling runners over just that paper and compare recovered characters:

```bash
python - <<'PY'
import pathlib, json
from lab import manifest, runners
name = input("filename: ").strip()
entry = manifest.entry_for(name)
path = manifest.corpus_dir() / name
stem = pathlib.Path(name).stem
for runner_name in ("docling-default", "docling-tuned"):
    out = runners.RUNNERS[runner_name](path, stem, entry["sha256"])
    chars = sum(len(b["text"]) for b in out["blocks"])
    print(f"{runner_name:16} {chars:8d} chars  {len(out['tables']):3d} tables  {out['wall_seconds']:6.1f}s")
PY
```

Expected: `docling-tuned` recovers more characters on a scanned paper and takes longer. If it recovers fewer, that is a finding worth writing down, not a bug to hide.

- [ ] **Step 7: Commit**

```bash
git add lab/runners.py lab/test_lab.py
git commit -m "feat: docling-tuned runner with OCR, accurate tables, explicit backend"
```

---

### Task 6: The pdfjs-node runner

**Files:**
- Create: `lab/pdfjs_runner.mjs`, `package.json`
- Modify: `lab/runners.py`, `lab/test_lab.py`

**Interfaces:**
- Consumes: `lab.runners.group_lines`, `lab.runners.finish`.
- Produces: `RUNNERS["pdfjs-node"]`, `lab.runners.PDFJS_SCRIPT: pathlib.Path`.
- `pdfjs_runner.mjs` stdout contract: `{"pages": [{"page": 1, "height": 792.0, "lines": [{"text": "...", "bbox": [x0, top, x1, bottom]}]}]}`, top-down coordinates, one JSON object on one line.

- [ ] **Step 1: Install the Node dependency**

```bash
cd ~/Desktop/Active\ Projects/No-RAGrets-v2
npm init -y
npm install pdfjs-dist@4.7.76
```

Then set `"type": "module"` in `package.json` so the `.mjs` import style works consistently, and commit `package.json` and `package-lock.json` (`node_modules/` is already gitignored).

- [ ] **Step 2: Write `lab/pdfjs_runner.mjs`**

```javascript
// Node side of the pdfjs-node runner.
//
// PORTED FROM: No-RAGrets-Master/ui/no-ragrets-ui/src/utils/pdfExtractor.ts
// That file cannot be imported here because it pulls in the UI app's build, so
// this reimplements the same pdf.js text-content call. If the two ever diverge,
// this lab is measuring something the product does not do — keep them in step.
//
// Usage: node lab/pdfjs_runner.mjs <path-to-pdf>   -> one line of JSON on stdout

import { readFileSync } from "node:fs";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const path = process.argv[2];
if (!path) {
  console.error("usage: node lab/pdfjs_runner.mjs <pdf>");
  process.exit(2);
}

const data = new Uint8Array(readFileSync(path));
const pdf = await getDocument({ data, useSystemFonts: true, isEvalSupported: false }).promise;

const pages = [];
for (let number = 1; number <= pdf.numPages; number += 1) {
  const page = await pdf.getPage(number);
  const viewport = page.getViewport({ scale: 1 });
  const content = await page.getTextContent();

  // Group text items into lines by their baseline, then sort left to right.
  const rows = new Map();
  for (const item of content.items) {
    if (!item.str || !item.str.trim()) continue;
    const x = item.transform[4];
    const baseline = item.transform[5];
    const top = viewport.height - baseline - (item.height || 0);
    const key = Math.round(top / 2);
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push({ x, top, width: item.width || 0, height: item.height || 0, str: item.str });
  }

  const lines = [];
  for (const key of [...rows.keys()].sort((a, b) => a - b)) {
    const items = rows.get(key).sort((a, b) => a.x - b.x);
    const text = items.map((i) => i.str).join(" ").replace(/\s+/g, " ").trim();
    if (!text) continue;
    lines.push({
      text,
      bbox: [
        Math.min(...items.map((i) => i.x)),
        Math.min(...items.map((i) => i.top)),
        Math.max(...items.map((i) => i.x + i.width)),
        Math.max(...items.map((i) => i.top + i.height)),
      ],
    });
  }
  pages.push({ page: number, height: viewport.height, lines });
}

process.stdout.write(JSON.stringify({ pages }) + "\n");
```

- [ ] **Step 3: Verify the Node script by hand before wiring Python to it**

Run: `node lab/pdfjs_runner.mjs fixtures/tiny.pdf`
Expected: one line of JSON with `pages[0].lines` containing `Methods`, `alpha 2`, `beta 3`, `Total 5`. If pdf.js warns on stderr that is fine — only stdout is parsed.

- [ ] **Step 4: Write the failing test**

Append to `lab/test_lab.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `python lab/test_lab.py`
Expected: `KeyError: 'pdfjs-node'`.

- [ ] **Step 6: Append the Python side to `lab/runners.py`**

```python
# ----------------------------------------------------------------- pdfjs-node

PDFJS_SCRIPT = pathlib.Path(__file__).parent / "pdfjs_runner.mjs"


@runner("pdfjs-node")
def run_pdfjs(pdf_path, paper_id, sha256):
    """The extractor the shipped app would use: pdf.js, in Node instead of a browser.

    Emits no tables at all — pdf.js has no table model. That is a real capability
    difference and the table metrics are what will price it.
    """
    started = time.time()
    finished = subprocess.run(
        ["node", str(PDFJS_SCRIPT), str(pdf_path)],
        capture_output=True, text=True, check=False,
    )
    if finished.returncode != 0:
        raise RuntimeError(f"pdfjs_runner.mjs exited {finished.returncode}: {finished.stderr[-500:]}")
    payload = json.loads(finished.stdout)

    blocks = []
    for page in payload["pages"]:
        for block in group_lines(page["lines"]):
            block["page"] = int(page["page"])
            blocks.append(block)

    return finish(paper_id, "pdfjs-node", _pdfjs_version(), sha256,
                  len(payload["pages"]), time.time() - started, blocks, [])


def _pdfjs_version():
    try:
        package = json.loads(pathlib.Path("node_modules/pdfjs-dist/package.json").read_text())
        return f"pdfjs-dist=={package['version']}"
    except Exception:
        return "pdfjs-dist==unknown"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `23/23 passed`.

- [ ] **Step 8: Commit**

```bash
git add lab/pdfjs_runner.mjs lab/runners.py lab/test_lab.py package.json package-lock.json
git commit -m "feat: pdfjs-node runner, the extractor the shipped app would use"
```

---

### Task 7: Text metrics — coverage, agreement, reading order, structure, cost

**Files:**
- Create: `lab/metrics.py`
- Modify: `lab/test_lab.py`

**Interfaces:**
- Consumes: `lab.ir.chars_per_page`, `lab.ir.page_text`, `lab.ir.TEXT_KINDS`.
- Produces: `lab.metrics.coverage(candidate, floor) -> dict`, `lab.metrics.agreement(a, b) -> dict`, `lab.metrics.reading_order(ir) -> dict`, `lab.metrics.structure_proxy(ir) -> dict`, `lab.metrics.cost(ir) -> dict`. All take IR dicts and return plain dicts of numbers — no classes, no state.

- [ ] **Step 1: Write the failing tests**

Append to `lab/test_lab.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python lab/test_lab.py`
Expected: `ModuleNotFoundError: No module named 'lab.metrics'`.

- [ ] **Step 3: Write `lab/metrics.py`**

```python
"""Label-free metrics over the IR.

No ground truth exists for this corpus, so nothing here compares against a gold
standard. Every function either compares a runner to another runner, or checks
an internal consistency property that can be wrong on its own terms.

Never aggregate these into one score. v1 did that and produced a "96.45%" whose
formula was never written down.
"""
import re
import statistics

from lab import ir

# A page recovering less than this share of the floor runner's characters is
# treated as lost rather than merely worse. This is the issue #4357 detector.
DROPPED_PAGE_RATIO = 0.10

# Below this the floor runner found nothing itself, so there is no ratio to take.
FLOOR_MIN_CHARS = 50


def coverage(candidate, floor):
    """Characters per page as a share of the pdfplumber floor."""
    got = ir.chars_per_page(candidate)
    base = ir.chars_per_page(floor)
    ratios = {}
    dropped = []
    for page, floor_chars in base.items():
        if floor_chars < FLOOR_MIN_CHARS:
            continue
        ratio = got.get(page, 0) / floor_chars
        ratios[page] = ratio
        if ratio < DROPPED_PAGE_RATIO:
            dropped.append(page)
    return {
        "chars_total": sum(got.values()),
        "pages_compared": len(ratios),
        "median_page_ratio": statistics.median(ratios.values()) if ratios else None,
        "min_page_ratio": min(ratios.values()) if ratios else None,
        "dropped_pages": sorted(dropped),
        "dropped_page_count": len(dropped),
    }


NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _grams(text, size=3):
    flat = NON_ALNUM.sub(" ", text.lower()).strip()
    flat = re.sub(r"\s+", " ", flat)
    return {flat[i:i + size] for i in range(len(flat) - size + 1)}


def agreement(a, b):
    """Per-page character 3-gram Jaccard between two runners.

    Disagreement localises a conflict; coverage then says which runner lost it.
    """
    scores = {}
    for page in range(1, min(a["pages"], b["pages"]) + 1):
        left = _grams(ir.page_text(a, page))
        right = _grams(ir.page_text(b, page))
        union = left | right
        if not union:
            continue
        scores[page] = len(left & right) / len(union)
    worst = sorted(scores.items(), key=lambda kv: kv[1])[:5]
    return {
        "pair": f"{a['runner']} vs {b['runner']}",
        "pages_compared": len(scores),
        "median": statistics.median(scores.values()) if scores else None,
        "worst_pages": [{"page": p, "score": round(s, 3)} for p, s in worst],
    }


# A paragraph ending in a hyphen, or in a lowercase letter with no terminator,
# was almost certainly cut off mid-word or mid-sentence.
# Known ceiling: a paragraph legitimately ending in an abbreviation reads as
# truncated. It is a comparative signal across runners, not an absolute count.
TRUNCATED = re.compile(r"(-|[a-z])$")

# Blocks may sit slightly above the previous one on the same line without that
# being a reading-order failure.
SAME_LINE_SLACK = 2.0


def reading_order(candidate):
    """How often consecutive blocks move forward down the page."""
    boxed = [b for b in candidate["blocks"] if b["bbox"]]
    pairs = 0
    forward = 0
    for previous, current in zip(boxed, boxed[1:]):
        pairs += 1
        if current["page"] != previous["page"]:
            forward += 1 if current["page"] > previous["page"] else 0
            continue
        goes_down = current["bbox"][1] >= previous["bbox"][1] - SAME_LINE_SLACK
        goes_right = current["bbox"][0] > previous["bbox"][2]
        if goes_down or goes_right:
            forward += 1

    truncated = sum(
        1 for b in candidate["blocks"]
        if b["kind"] == "paragraph" and TRUNCATED.search(b["text"].strip())
    )
    return {
        "blocks": len(candidate["blocks"]),
        "blocks_with_bbox": len(boxed),
        "monotonic_fraction": (forward / pairs) if pairs else None,
        "blocks_ending_midword": truncated,
    }


SECTION_PATTERNS = {
    "abstract": re.compile(r"\babstract\b", re.I),
    "introduction": re.compile(r"\bintroduction\b", re.I),
    "methods": re.compile(r"\b(methods|methodology|materials and methods)\b", re.I),
    "results": re.compile(r"\bresults\b", re.I),
    "discussion": re.compile(r"\bdiscussion\b", re.I),
    "references": re.compile(r"\b(references|bibliography|literature cited)\b", re.I),
}


def structure_proxy(candidate):
    """Are the six sections a paper essentially always has each found once?

    A miss means the header was not detected, which downstream means the chunker
    had nothing to split on.
    """
    headers = [b["text"] for b in candidate["blocks"] if b["kind"] == "section_header"]
    counts = {
        name: sum(1 for header in headers if pattern.search(header))
        for name, pattern in SECTION_PATTERNS.items()
    }
    return {
        "section_headers": len(headers),
        "counts": counts,
        "found_exactly_once": sum(1 for n in counts.values() if n == 1),
        "missing": sorted(name for name, n in counts.items() if n == 0),
    }


def cost(candidate):
    """Wall clock. This is the issue #4174 detector."""
    pages = candidate["pages"]
    return {
        "wall_seconds": candidate["wall_seconds"],
        "seconds_per_page": (candidate["wall_seconds"] / pages) if pages else None,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `30/30 passed`.

- [ ] **Step 5: Commit**

```bash
git add lab/metrics.py lab/test_lab.py
git commit -m "feat: coverage, agreement, reading order, structure and cost metrics"
```

---

### Task 8: Table and chunk metrics

The spec lists rectangularity as a table-structure metric. It is dropped here and the reason is recorded in the code: `ir.validate` already rejects a non-rectangular table, and the runners pad short rows, so rectangularity would read 1.0 for every runner by construction. Empty-cell density measures the same underlying failure — a table whose structure was misread — and can actually vary.

**Files:**
- Modify: `lab/metrics.py`, `lab/test_lab.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `lab.metrics.parse_number(raw) -> float | None`, `lab.metrics.table_arithmetic(ir) -> dict`, `lab.metrics.table_structure(ir) -> dict`, `lab.metrics.chunk_health(ir) -> dict`.

- [ ] **Step 1: Write the failing tests**

The corrupted-table case is the point of this task. A metric that cannot fail is not a metric.

Append to `lab/test_lab.py`:

```python
def ir_with_table(cells, rows=None, cols=None):
    rows = rows if rows is not None else len(cells)
    cols = cols if cols is not None else (len(cells[0]) if cells else 0)
    return {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "blocks": [], "chunks": [],
        "tables": [{"page": 1, "rows": rows, "cols": cols, "cells": cells, "caption": None}],
    }


GOOD_TABLE = [
    ["condition", "yield", "cost"],
    ["a", "10", "1.5"],
    ["b", "15", "2.5"],
    ["Total", "25", "4.0"],
]


def test_parse_number_handles_the_formats_papers_actually_use():
    assert metrics.parse_number("1,234") == 1234.0
    assert metrics.parse_number("(12.5)") == -12.5
    assert metrics.parse_number("−3") == -3.0
    assert metrics.parse_number("45%") == 45.0
    assert metrics.parse_number("n/a") is None
    assert metrics.parse_number("") is None
    assert metrics.parse_number(None) is None


def test_table_arithmetic_passes_a_table_that_reconciles():
    out = metrics.table_arithmetic(ir_with_table(GOOD_TABLE))
    assert out["checked"] == 2, out          # the yield column and the cost column
    assert out["passed"] == 2, out
    assert out["pass_rate"] == 1.0


def test_table_arithmetic_fails_a_corrupted_cell():
    broken = [row[:] for row in GOOD_TABLE]
    broken[1][1] = "100"                     # 100 + 15 != 25
    out = metrics.table_arithmetic(ir_with_table(broken))
    assert out["passed"] < out["checked"], out
    assert out["failures"], "a failing check must be reported, not silently dropped"


def test_table_arithmetic_checks_a_total_column_too():
    cells = [
        ["site", "q1", "q2", "Total"],
        ["north", "2", "3", "5"],
        ["south", "4", "1", "5"],
    ]
    out = metrics.table_arithmetic(ir_with_table(cells))
    assert out["checked"] == 2, out
    assert out["passed"] == 2, out


def test_table_arithmetic_reports_nothing_checkable_as_none():
    out = metrics.table_arithmetic(ir_with_table([["a", "b"], ["c", "d"]]))
    assert out["checked"] == 0
    assert out["pass_rate"] is None


def test_table_structure_measures_empty_density():
    sparse = [["a", "", ""], ["", "", ""]]
    out = metrics.table_structure(ir_with_table(sparse))
    assert out["tables"] == 1
    assert out["empty_cell_ratio"] > 0.8, out
    dense = metrics.table_structure(ir_with_table(GOOD_TABLE))
    assert dense["empty_cell_ratio"] == 0.0
    assert dense["numeric_cell_ratio"] > 0.4, dense


def test_table_structure_on_a_runner_with_no_tables():
    out = metrics.table_structure(two_page_ir("a", "b"))
    assert out["tables"] == 0
    assert out["empty_cell_ratio"] is None


def test_chunk_health_flags_orphans_and_midsentence_starts():
    candidate = {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "tables": [],
        "blocks": [
            {"page": 1, "kind": "section_header", "text": "Methods", "bbox": None, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "long enough sentence here", "bbox": None, "order": 1},
        ],
        "chunks": [
            {"id": 0, "text": "tiny", "block_ids": [1], "section": "Methods", "chars": 4},
            {"id": 1, "text": "and this one starts mid sentence because it is lowercase",
             "block_ids": [1], "section": "Methods", "chars": 55},
        ],
    }
    out = metrics.chunk_health(candidate)
    assert out["orphan_chunks"] == 1, out
    assert out["midsentence_starts"] == 2, out
    assert out["straddling_chunks"] == 0, out
    assert out["median_chars"] is not None


def test_chunk_health_detects_a_chunk_spanning_a_section_header():
    candidate = {
        "paper_id": "p", "runner": "x", "runner_version": "v", "pdf_sha256": "0" * 64,
        "pages": 1, "wall_seconds": 1.0, "tables": [],
        "blocks": [
            {"page": 1, "kind": "paragraph", "text": "Before the header.", "bbox": None, "order": 0},
            {"page": 1, "kind": "section_header", "text": "Results", "bbox": None, "order": 1},
            {"page": 1, "kind": "paragraph", "text": "After the header.", "bbox": None, "order": 2},
        ],
        "chunks": [
            {"id": 0, "text": "Before the header. After the header.", "block_ids": [0, 2],
             "section": "(front matter)", "chars": 35},
        ],
    }
    assert metrics.chunk_health(candidate)["straddling_chunks"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python lab/test_lab.py`
Expected: `AttributeError: module 'lab.metrics' has no attribute 'parse_number'`.

- [ ] **Step 3: Append to `lab/metrics.py`**

```python
# ------------------------------------------------------------------- tables

TOTAL_WORD = re.compile(r"\b(total|totals|sum|sums|overall)\b", re.I)

# 1% relative, or 0.01 absolute when the total is near zero. Papers round their
# own published totals, so a tighter tolerance would fail on correct tables.
TOLERANCE_RELATIVE = 0.01
TOLERANCE_ABSOLUTE = 0.01

# Row 0 is assumed to be a header row, and column 0 a label column.
# Known ceiling: a table with two header rows will have its first data row read
# as a header and excluded from the sum. Upgrade path is detecting header depth
# by numeric density per row.
HEADER_ROWS = 1
LABEL_COLS = 1


def parse_number(raw):
    """Parse the number formats papers actually print, or return None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("%", "").replace(" ", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "")
    if text in ("", "-", "."):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _total_series(table):
    """Yield every (values, total) pair a labelled total row or column implies."""
    cells, rows, cols = table["cells"], table["rows"], table["cols"]

    for r in range(HEADER_ROWS, rows):
        labels = [cells[r][c] or "" for c in range(min(LABEL_COLS + 1, cols))]
        if not any(TOTAL_WORD.search(label) for label in labels):
            continue
        for c in range(cols):
            total = parse_number(cells[r][c])
            values = [v for v in (parse_number(cells[i][c]) for i in range(HEADER_ROWS, r))
                      if v is not None]
            if total is None or len(values) < 2:
                continue
            yield {"axis": "row", "row": r, "col": c, "values": values, "total": total}

    for c in range(LABEL_COLS, cols):
        labels = [cells[r][c] or "" for r in range(min(HEADER_ROWS + 1, rows))]
        if not any(TOTAL_WORD.search(label) for label in labels):
            continue
        for r in range(rows):
            total = parse_number(cells[r][c])
            values = [v for v in (parse_number(cells[r][i]) for i in range(LABEL_COLS, c))
                      if v is not None]
            if total is None or len(values) < 2:
                continue
            yield {"axis": "col", "row": r, "col": c, "values": values, "total": total}


def table_arithmetic(candidate):
    """Does a labelled total actually equal the sum of its series?

    The only metric here that can be flatly right or wrong with no labels, so it
    carries the most weight in the report. A misread cell, a dropped row, or a
    column shifted by one all show up as a failure.
    """
    checked = 0
    passed = 0
    failures = []
    for index, table in enumerate(candidate["tables"]):
        for series in _total_series(table):
            total = series["total"]
            checked += 1
            limit = max(abs(total) * TOLERANCE_RELATIVE, TOLERANCE_ABSOLUTE)
            if abs(sum(series["values"]) - total) <= limit:
                passed += 1
            elif len(failures) < 20:
                failures.append({
                    "table": index, "page": table["page"], "axis": series["axis"],
                    "row": series["row"], "col": series["col"],
                    "summed": round(sum(series["values"]), 4), "printed": total,
                })
    return {
        "checked": checked,
        "passed": passed,
        "pass_rate": (passed / checked) if checked else None,
        "failures": failures,
    }


NUMERIC_CELL = re.compile(r"\d")


def table_structure(candidate):
    """Table count and cell density.

    Rectangularity is deliberately not measured: ir.validate rejects a ragged
    table and the runners pad short rows, so it would read 1.0 for every runner.
    Empty-cell density catches the same failure — a misread grid — and can vary.
    """
    tables = candidate["tables"]
    total_cells = sum(t["rows"] * t["cols"] for t in tables)
    if not tables or not total_cells:
        return {
            "tables": len(tables), "cells": total_cells,
            "empty_cell_ratio": None, "numeric_cell_ratio": None,
            "median_rows": None, "median_cols": None,
        }
    flat = [cell for t in tables for row in t["cells"] for cell in row]
    empty = sum(1 for cell in flat if not (cell or "").strip())
    numeric = sum(1 for cell in flat if NUMERIC_CELL.search(cell or ""))
    return {
        "tables": len(tables),
        "cells": total_cells,
        "empty_cell_ratio": empty / len(flat),
        "numeric_cell_ratio": numeric / len(flat),
        "median_rows": statistics.median([t["rows"] for t in tables]),
        "median_cols": statistics.median([t["cols"] for t in tables]),
    }


# ------------------------------------------------------------------- chunks

ORPHAN_CHARS = 100


def chunk_health(candidate):
    """Are the chunks something a retriever could use?"""
    chunks = candidate["chunks"]
    if not chunks:
        return {
            "chunks": 0, "median_chars": None, "p10_chars": None, "p90_chars": None,
            "orphan_chunks": 0, "midsentence_starts": 0, "straddling_chunks": 0,
        }

    sizes = sorted(c["chars"] for c in chunks)
    header_orders = {b["order"] for b in candidate["blocks"] if b["kind"] == "section_header"}

    def straddles(chunk):
        ids = chunk.get("block_ids") or []
        if len(ids) < 2:
            return False
        low, high = min(ids), max(ids)
        return any(low < order < high for order in header_orders)

    def quantile(fraction):
        return sizes[min(len(sizes) - 1, int(fraction * len(sizes)))]

    return {
        "chunks": len(chunks),
        "median_chars": statistics.median(sizes),
        "p10_chars": quantile(0.10),
        "p90_chars": quantile(0.90),
        "orphan_chunks": sum(1 for c in chunks if c["chars"] < ORPHAN_CHARS),
        "midsentence_starts": sum(1 for c in chunks if c["text"][:1].islower()),
        "straddling_chunks": sum(1 for c in chunks if straddles(c)),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `39/39 passed`, including `test_table_arithmetic_fails_a_corrupted_cell`.

- [ ] **Step 5: Commit**

```bash
git add lab/metrics.py lab/test_lab.py
git commit -m "feat: table arithmetic, table density and chunk health metrics"
```

---

### Task 9: The report and the remaining CLI commands

**Files:**
- Create: `lab/report.py`
- Modify: `lab/cli.py`, `lab/test_lab.py`

**Interfaces:**
- Consumes: everything in `lab.metrics`, `lab.runners.import_docling_json`.
- Produces: `lab.report.load_results(runner: str) -> dict[str, dict]`, `lab.report.score(results_by_runner: dict, floor: str = "pdfplumber") -> dict`, `lab.report.render(scored: dict) -> str`.
- Produces CLI: `python -m lab compare`, `python -m lab import-baseline <dir>`.

- [ ] **Step 1: Write the failing test**

Append to `lab/test_lab.py`:

```python
from lab import report


def test_render_produces_a_row_per_runner_and_no_composite_score():
    floor = two_page_ir("x" * 400, "y" * 400, runner_name="pdfplumber")
    better = two_page_ir("x" * 400, "y" * 400, runner_name="docling-tuned")
    worse = two_page_ir("x" * 400, "", runner_name="pdfjs-node")
    results = {
        "pdfplumber": {"p": floor},
        "docling-tuned": {"p": better},
        "pdfjs-node": {"p": worse},
    }
    scored = report.score(results)
    text = report.render(scored)
    for name in results:
        assert name in text, f"{name} missing from the report"
    assert "dropped" in text.lower()
    assert "overall score" not in text.lower(), "no composite score, ever"
    assert scored["runners"]["pdfjs-node"]["coverage"]["dropped_page_count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python lab/test_lab.py`
Expected: `ModuleNotFoundError: No module named 'lab.report'`.

- [ ] **Step 3: Write `lab/report.py`**

```python
"""Aggregate per-paper results into results/REPORT.md.

Only aggregates are written. results/*.jsonl holds the full text of every paper
and stays gitignored — committing it would make this repo a dataset instead of
a tool.
"""
import json
import pathlib
import statistics

from lab import metrics

RESULTS_DIR = pathlib.Path("results")
REPORT_PATH = RESULTS_DIR / "REPORT.md"
FLOOR_RUNNER = "pdfplumber"


def load_results(runner):
    path = RESULTS_DIR / f"{runner}.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["paper_id"]] = record
    return out


def available_runners():
    return sorted(p.stem for p in RESULTS_DIR.glob("*.jsonl"))


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def score(results_by_runner, floor=FLOOR_RUNNER):
    """Per-runner aggregates plus the per-paper outliers worth looking at."""
    floor_results = results_by_runner.get(floor, {})
    scored = {"floor": floor, "runners": {}, "pairs": [], "outliers": {}}

    for runner, papers in sorted(results_by_runner.items()):
        per_paper = {}
        for paper_id, candidate in papers.items():
            base = floor_results.get(paper_id)
            per_paper[paper_id] = {
                "coverage": metrics.coverage(candidate, base) if base else None,
                "reading_order": metrics.reading_order(candidate),
                "structure": metrics.structure_proxy(candidate),
                "tables": metrics.table_structure(candidate),
                "arithmetic": metrics.table_arithmetic(candidate),
                "chunks": metrics.chunk_health(candidate),
                "cost": metrics.cost(candidate),
            }

        covered = [p["coverage"] for p in per_paper.values() if p["coverage"]]
        arithmetic_checked = sum(p["arithmetic"]["checked"] for p in per_paper.values())
        arithmetic_passed = sum(p["arithmetic"]["passed"] for p in per_paper.values())

        scored["runners"][runner] = {
            "papers": len(per_paper),
            "coverage": {
                "median_page_ratio": _mean([c["median_page_ratio"] for c in covered]),
                "dropped_page_count": sum(c["dropped_page_count"] for c in covered),
                "chars_total": sum(c["chars_total"] for c in covered),
            },
            "reading_order": {
                "monotonic_fraction": _mean([p["reading_order"]["monotonic_fraction"]
                                             for p in per_paper.values()]),
                "blocks_ending_midword": sum(p["reading_order"]["blocks_ending_midword"]
                                             for p in per_paper.values()),
            },
            "structure": {
                "found_exactly_once": _mean([p["structure"]["found_exactly_once"]
                                             for p in per_paper.values()]),
            },
            "tables": {
                "total": sum(p["tables"]["tables"] for p in per_paper.values()),
                "empty_cell_ratio": _mean([p["tables"]["empty_cell_ratio"]
                                           for p in per_paper.values()]),
            },
            "arithmetic": {
                "checked": arithmetic_checked,
                "passed": arithmetic_passed,
                "pass_rate": (arithmetic_passed / arithmetic_checked) if arithmetic_checked else None,
            },
            "chunks": {
                "total": sum(p["chunks"]["chunks"] for p in per_paper.values()),
                "median_chars": _mean([p["chunks"]["median_chars"] for p in per_paper.values()]),
                "orphan_chunks": sum(p["chunks"]["orphan_chunks"] for p in per_paper.values()),
                "straddling_chunks": sum(p["chunks"]["straddling_chunks"] for p in per_paper.values()),
            },
            "cost": {
                "seconds_per_page": _mean([p["cost"]["seconds_per_page"] for p in per_paper.values()]),
            },
        }

        worst = sorted(
            ((paper_id, p["coverage"]["median_page_ratio"])
             for paper_id, p in per_paper.items()
             if p["coverage"] and p["coverage"]["median_page_ratio"] is not None),
            key=lambda kv: kv[1],
        )[:5]
        scored["outliers"][runner] = [{"paper_id": pid, "median_page_ratio": round(r, 3)}
                                      for pid, r in worst]

    names = sorted(results_by_runner)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            shared = set(results_by_runner[left]) & set(results_by_runner[right])
            scores = [metrics.agreement(results_by_runner[left][p], results_by_runner[right][p])["median"]
                      for p in sorted(shared)]
            scored["pairs"].append({
                "pair": f"{left} vs {right}",
                "papers": len(shared),
                "median_agreement": _mean(scores),
            })
    return scored


def _cell(value, digits=3):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render(scored):
    lines = [
        "# Ingestion Lab Report",
        "",
        f"Floor runner: `{scored['floor']}`. Coverage is measured against it, so its own "
        "coverage row is 1.0 by definition.",
        "",
        "No column is a quality score and no column should be averaged with another. "
        "Read `arith pass` first — it is the only column that can be flatly wrong.",
        "",
        "| runner | papers | cov. median | dropped pages | chars | order monotonic | "
        "midword | sections/6 | tables | empty cells | arith checked | arith pass | "
        "chunks | orphans | s/page |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for runner, s in scored["runners"].items():
        lines.append(
            f"| `{runner}` | {s['papers']} | {_cell(s['coverage']['median_page_ratio'])} | "
            f"{s['coverage']['dropped_page_count']} | {s['coverage']['chars_total']} | "
            f"{_cell(s['reading_order']['monotonic_fraction'])} | "
            f"{s['reading_order']['blocks_ending_midword']} | "
            f"{_cell(s['structure']['found_exactly_once'], 2)} | {s['tables']['total']} | "
            f"{_cell(s['tables']['empty_cell_ratio'])} | {s['arithmetic']['checked']} | "
            f"{_cell(s['arithmetic']['pass_rate'])} | {s['chunks']['total']} | "
            f"{s['chunks']['orphan_chunks']} | {_cell(s['cost']['seconds_per_page'], 2)} |"
        )

    lines += ["", "## Cross-runner agreement", "",
              "| pair | papers | median 3-gram agreement |", "|---|---|---|"]
    for pair in scored["pairs"]:
        lines.append(f"| {pair['pair']} | {pair['papers']} | {_cell(pair['median_agreement'])} |")

    lines += ["", "## Worst five papers per runner, by coverage", ""]
    for runner, rows in scored["outliers"].items():
        listed = ", ".join(f"{r['paper_id']} ({r['median_page_ratio']})" for r in rows) or "—"
        lines.append(f"- `{runner}`: {listed}")

    lines += ["", "## Chunk straddling", ""]
    for runner, s in scored["runners"].items():
        lines.append(f"- `{runner}`: {s['chunks']['straddling_chunks']} chunks cross a section header")
    lines.append("")
    return "\n".join(lines)


def write(floor=FLOOR_RUNNER):
    results = {runner: load_results(runner) for runner in available_runners()}
    results = {k: v for k, v in results.items() if v}
    if not results:
        raise SystemExit("no results found — run at least one runner first")
    scored = score(results, floor=floor)
    RESULTS_DIR.mkdir(exist_ok=True)
    REPORT_PATH.write_text(render(scored))
    return scored
```

- [ ] **Step 4: Add `compare` and `import-baseline` to `lab/cli.py`**

Add these two functions above `build_parser`:

```python
def cmd_compare(args):
    from lab import report

    scored = report.write(floor=args.floor)
    print(f"wrote {report.REPORT_PATH}")
    for runner, summary in scored["runners"].items():
        rate = summary["arithmetic"]["pass_rate"]
        rate_text = "—" if rate is None else f"{rate:.3f}"
        print(f"  {runner:16} {summary['papers']:3d} papers  "
              f"arith {summary['arithmetic']['checked']:4d} checked, pass {rate_text}  "
              f"dropped pages {summary['coverage']['dropped_page_count']}")
    return 0


def cmd_import_baseline(args):
    """Import DoclingDocument JSON produced earlier by a bare DocumentConverter."""
    from lab import manifest, runners

    source = pathlib.Path(args.directory).expanduser()
    entries = manifest.load()
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "docling-default.jsonl"

    written = skipped = 0
    with out_path.open("w") as fh:
        for entry in entries:
            stem = pathlib.Path(entry["filename"]).stem
            json_path = source / f"{stem}.json"
            if not json_path.exists():
                print(f"MISSING  {stem}.json")
                skipped += 1
                continue
            record = runners.import_docling_json(json_path, stem, entry["sha256"])
            fh.write(json.dumps(record) + "\n")
            written += 1

    print(f"imported {written} baselines to {out_path} ({skipped} missing)")
    return 0 if skipped == 0 else 1
```

And register both inside `build_parser`:

```python
    c = sub.add_parser("compare", help="aggregate results into results/REPORT.md")
    c.add_argument("--floor", default="pdfplumber")
    c.set_defaults(func=cmd_compare)

    i = sub.add_parser("import-baseline", help="import existing DoclingDocument JSON as the baseline")
    i.add_argument("directory", help="e.g. ../No-RAGrets-Master/data/docling_json")
    i.set_defaults(func=cmd_import_baseline)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python lab/test_lab.py`
Expected: `40/40 passed`.

- [ ] **Step 6: Commit**

```bash
git add lab/report.py lab/cli.py lab/test_lab.py
git commit -m "feat: report aggregation, compare and import-baseline commands"
```

---

### Task 10: Full corpus run and the acceptance check

**Files:**
- Create: `results/REPORT.md`, `README.md` (replace the shell's placeholder)
- Modify: none

**Interfaces:** none produced. This task runs the lab and writes down what it found.

- [ ] **Step 1: Import the baseline and confirm it reproduces**

```bash
export NORAGRETS_CORPUS=~/Desktop/Active\ Projects/No-RAGrets-Master/data/papers
python -m lab import-baseline ~/Desktop/Active\ Projects/No-RAGrets-Master/data/docling_json
```

Expected: 47 imported, 0 missing. The two orphaned JSON files in that directory (`Nguyen et al. 2021`, `Vercherskaya et al. 2001`) have no PDF, so they are simply never asked for — the manifest drives the loop.

Then satisfy acceptance criterion 3 — a re-run from the PDF must reproduce the imported baseline structurally. `content_hash` cannot be used directly because `runner_version` differs by design (`"docling==2.60.0 (imported)"`), so compare blocks and tables only:

```bash
python - <<'PY'
import hashlib, json, pathlib
from lab import manifest, report, runners

def structural(record):
    payload = {"blocks": [{k: b[k] for k in ("page", "kind", "text")} for b in record["blocks"]],
               "tables": [{k: t[k] for k in ("page", "rows", "cols", "cells")} for t in record["tables"]]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

imported = report.load_results("docling-default")
paper_id = sorted(imported)[0]
entry = manifest.entry_for(paper_id + ".pdf")
fresh = runners.RUNNERS["docling-default"](manifest.corpus_dir() / entry["filename"], paper_id, entry["sha256"])
print(paper_id)
print("imported:", structural(imported[paper_id]))
print("re-run:  ", structural(fresh))
print("MATCH" if structural(imported[paper_id]) == structural(fresh) else "MISMATCH")
PY
```

Expected: `MATCH`. If it mismatches, the installed docling is not the version that produced the JSON — check `pip show docling` reports 2.60.0 before doing anything else. Record the outcome either way; a mismatch means the baseline must be re-run rather than imported, which costs compute but not correctness.

- [ ] **Step 2: Run the three remaining runners over the full corpus**

```bash
python -m lab run pdfplumber
python -m lab run pdfjs-node
python -m lab run docling-tuned      # slowest; expect tens of minutes
```

Expected: 47 results each, no `FAILED` lines. Investigate any failure before continuing — a runner that skipped papers produces a report comparing different corpora per row.

- [ ] **Step 3: Verify every result validates**

```bash
python - <<'PY'
from lab import ir, report
for runner in report.available_runners():
    records = report.load_results(runner)
    for record in records.values():
        ir.validate(record)
    print(f"{runner:16} {len(records):3d} papers, all valid")
PY
```

Expected: four lines, 47 each. This is acceptance criterion 1.

- [ ] **Step 4: Write the report**

```bash
python -m lab compare
```

Expected: `results/REPORT.md` with all eight metric families across four runners. This is acceptance criterion 2.

- [ ] **Step 5: Answer the question the lab was built for**

Read `results/REPORT.md` and append a short `## Findings` section to it by hand, stating in plain English:

1. Whether `docling-tuned` beats `docling-default` on coverage, dropped pages, and table arithmetic — and what it cost in seconds per page.
2. Whether `pdfjs-node` is within tolerance of `docling-tuned` on coverage and table structure. This is acceptance criterion 5 and it decides whether the browser-side, zero-server hosting design survives the re-scope. `pdfjs-node` produces no tables at all by construction, so state the coverage answer and the table answer separately rather than blending them.
3. Any paper where all four runners disagree — those are the PDFs worth looking at by eye.

Do not invent a headline ratio. If a number needs a caveat, write the caveat.

- [ ] **Step 6: Replace the README**

The repo shell's README is a placeholder. Replace it with: what the lab measures, why there are no labels, the three commands (`manifest build`, `run <runner>`, `compare`), the `NORAGRETS_CORPUS` requirement, the docling pin and why, and a pointer to the spec and this plan. Keep it short — under 60 lines. State plainly that the corpus is not in the repo and that this is a tool, not a dataset.

- [ ] **Step 7: Run the full test suite one last time**

Run: `python lab/test_lab.py`
Expected: `40/40 passed`. This is acceptance criterion 4.

- [ ] **Step 8: Commit**

```bash
git add results/REPORT.md README.md
git commit -m "feat: full-corpus run, report, and findings"
```

Note: only `results/REPORT.md` is committed. `git status` must show no `results/*.jsonl` — if it does, the gitignore from Task 1 was not applied.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: purpose and constraints to Global Constraints; IR to Task 1; manifest to Task 2; the four runners to Tasks 3–6; the eight metric families to Tasks 7–8 (coverage, table arithmetic, table structure, cross-runner agreement, reading order, structure proxy, chunk health, determinism-and-cost); output to Task 9; testing to every task; acceptance criteria 1–5 to Task 10.

**Two deliberate deviations from the spec**, both recorded in code comments where a future reader will hit them:

1. **Rectangularity is dropped** from table structure (Task 8). `ir.validate` rejects ragged tables and runners pad short rows, so it would read 1.0 for every runner by construction. Empty-cell density replaces it and measures the same failure.
2. **Determinism is tested, not reported.** The spec lists determinism alongside cost as metric family eight. `content_hash` exists (Task 1) and is unit-tested, but `REPORT.md` carries only the cost half. A determinism column would need every runner run twice over 47 papers, which doubles the slowest step to prove something that has no source of randomness. Run `--force` twice on a three-paper subset if it ever needs demonstrating.

**Files, three of which the spec's sketch did not name** — `ir.py`, `manifest.py`, `report.py` — split out because three or more modules import each, and the IR is the interface the rest of No RAGrets v2 consumes.

**Known ceilings marked in code**, each with an upgrade path: regex sentence splitting, font-blind header classification, single-header-row table assumption, the scanned-page character heuristic, and the truncated-paragraph regex.
