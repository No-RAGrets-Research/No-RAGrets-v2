# Part 2a — Reader and Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A static site that reads the 47-paper corpus from a prebuilt bundle, searches it semantically and lexically, answers questions through one free Cloudflare Worker, and shows every citation highlighted on the real PDF page it came from.

**Architecture:** `python -m lab export` resolves each chunk's block references into page rectangles, embeds chunk text offline, and writes a bundle (manifest, papers, chunks, int8 vectors, PDFs). A Vite + React site loads that bundle by id and runs all retrieval in the browser. Only answering leaves the browser: the top-k chunk texts go to a Worker that holds the model key and returns an answer with citation indices.

**Tech Stack:** Python 3.12.8 (`./.venv/bin/python`), docling 2.60.0 (already pinned), fastembed for offline embeddings, Vite + React + TypeScript + Tailwind, react-pdf, `@huggingface/transformers` for in-browser query embedding, Cloudflare Workers + Workers KV, `llm-kit` for the Groq call, vitest for frontend tests, plain asserts for Python.

**Spec:** `docs/superpowers/specs/2026-10-01-part2a-reader-design.md`

## Global Constraints

- Interpreter is `./.venv/bin/python`, never a bare `python`. arm64 Python 3.12.8, docling pinned at 2.60.0.
- `export NORAGRETS_CORPUS="$HOME/Desktop/Active Projects/No-RAGrets-Master/data/papers"` before any command that touches the corpus.
- **Zero cost.** Free hosting, free-tier model, no service that can bill. One Cloudflare Worker on the free tier is the only server-side component.
- **Search, reading and provenance must work with the Worker absent.** Only answering may depend on it.
- **No composite scores.** Semantic and lexical rankings are separate everywhere — no blended number in any file, column, or variable.
- Embedding model is **BAAI/bge-small-en-v1.5** on the Python side and **Xenova/bge-small-en-v1.5** in the browser. Same weights, 384 dimensions. Pooling must match on both sides (see Task 7).
- `bbox` is `[x0, top, x1, bottom]` in **top-down PDF points**. There is no coordinate flip anywhere in the frontend; the flip happens once in `lab/runners.py:300`.
- Python tests are plain asserts appended to `lab/test_lab.py`, collected by name at call time. The `if __name__ == "__main__"` guard must stay the LAST thing in that file or appended tests are silently never collected.
- `LlmError` imports from the `llm-kit` root entry, not from `llm-kit/openai-compat`. Importing it from the subpath is a `SyntaxError`.
- Commit after every task. Never commit `results/*.jsonl`, `bundles/*/vectors.bin`, or `bundles/*/pdfs/` — they are gitignored and travel as a Release asset.

## File Structure

**Python, offline bundle build:**
- `lab/export.py` — resolves chunk regions, writes manifest/papers/chunks, copies PDFs. One responsibility: turn one runner's results into a bundle directory.
- `lab/embed.py` — embeds chunk text, quantizes to int8, writes `vectors.bin`, reports quantization error. Kept separate from `export.py` because it owns the one heavy dependency and is the only part that can be skipped with `--no-embed`.
- `lab/cli.py` — add the `export` subcommand. Existing file, follow its `cmd_*` + `build_parser` pattern.
- `lab/test_lab.py` — append tests. Existing file, plain asserts.
- `tools/verify_highlights.py` — one-off visual check that docling bboxes land on the rendered page. Not a test.
- `requirements.txt` — add fastembed at its resolved version.

**Frontend, `web/`:**
- `web/src/bundle.ts` — bundle types, loader, and the `embed_model` guard. Everything downstream consumes its types.
- `web/src/geometry.ts` — `rectToStyle`. The only place a rect becomes pixels.
- `web/src/retrieval/bm25.ts` — lexical index and ranking.
- `web/src/retrieval/vectors.ts` — int8 → Float32Array dequantization and cosine top-k.
- `web/src/retrieval/embedder.ts` — lazy transformers.js query embedding.
- `web/src/retrieval/index.ts` — `search()`, the single entry point both modes come through.
- `web/src/ask.ts` — the Worker client and its error mapping.
- `web/src/components/{PaperList,Reader,Highlight,SearchPanel,AskBox}.tsx` — one responsibility each.
- `web/src/App.tsx`, `web/src/main.tsx` — routes and mount.

**Worker, `worker/`:**
- `worker/src/prompt.ts` — pure: builds the message list, maps `[n]` back to chunk ids.
- `worker/src/caps.ts` — pure: cap decisions against a KV-shaped interface.
- `worker/src/index.ts` — thin fetch handler. Everything testable lives in the two files above.
- `worker/wrangler.toml` — bindings and the KV namespace.

**CI:**
- `.github/workflows/pages.yml` — downloads the bundle Release asset, builds `web/`, deploys to Pages.

---

### Task 1: `lab export` — the text bundle

Writes everything except vectors: manifest, papers, chunks with resolved page rectangles, and the PDFs. This is the task that deletes v1's whole class of provenance bug, by resolving block references at build time where both lists are in hand.

**Files:**
- Create: `lab/export.py`
- Modify: `lab/cli.py` (add `cmd_export` and its subparser)
- Test: `lab/test_lab.py` (append)

**Interfaces:**
- Consumes: `lab.manifest.load()`, `lab.manifest.corpus_dir()`, the IR records in `results/<runner>.jsonl`. In the IR, `chunk["block_ids"]` are **positional indices** into that paper's `blocks[]`.
- Produces: `export.chunk_regions(record, chunk) -> list[dict]` and `export.write_bundle(records, entries, out_dir, corpus_dir) -> dict` (the manifest it wrote). Task 2 calls `write_bundle` and then adds vectors.

- [ ] **Step 1: Write the failing test for region resolution**

Append to `lab/test_lab.py`:

```python
from lab import export


def ir_with_pages(paper_id="Two Page Paper"):
    """An IR whose one chunk spans a page break, which is the case that breaks
    naive geometry: regions must group by page, not flatten into one list."""
    return {
        "paper_id": paper_id, "runner": "docling-default", "runner_version": "test",
        "pdf_sha256": "0" * 64, "pages": 2, "wall_seconds": 1.0,
        "blocks": [
            {"page": 1, "kind": "section_header", "text": "Results", "bbox": [10, 10, 90, 20], "order": 0},
            {"page": 1, "kind": "paragraph", "text": "First half.", "bbox": [10, 30, 90, 50], "order": 1},
            {"page": 2, "kind": "paragraph", "text": "Second half.", "bbox": [10, 60, 90, 80], "order": 2},
            {"page": 2, "kind": "paragraph", "text": "Unrelated.", "bbox": None, "order": 3},
        ],
        "tables": [],
        "chunks": [
            {"id": 0, "text": "First half. Second half.", "block_ids": [1, 2],
             "section": "Results", "chars": 24},
            {"id": 1, "text": "Unrelated.", "block_ids": [3], "section": "Results", "chars": 10},
        ],
    }


def test_chunk_regions_group_rects_by_page():
    record = ir_with_pages()
    regions = export.chunk_regions(record, record["chunks"][0])
    assert [r["page"] for r in regions] == [1, 2], regions
    assert regions[0]["rects"] == [[10, 30, 90, 50]], regions
    assert regions[1]["rects"] == [[10, 60, 90, 80]], regions


def test_chunk_regions_is_empty_when_no_block_has_geometry():
    record = ir_with_pages()
    assert export.chunk_regions(record, record["chunks"][1]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -3`
Expected: FAIL on both new tests with `ModuleNotFoundError` or `AttributeError` naming `export`.

- [ ] **Step 3: Write `chunk_regions`**

Create `lab/export.py`:

```python
"""Turn one runner's results into a bundle the static reader can load.

The one job that matters here: resolve `chunk["block_ids"]` into page
rectangles NOW, at build time, where the chunk and `blocks[]` are both in
hand. v1 shipped block references to the browser and spent three tiers of
fuzzy text matching trying to resolve them there.
"""
import hashlib
import json
import pathlib
import shutil


def chunk_regions(record, chunk):
    """[{page, rects: [[x0, top, x1, bottom], ...]}, ...] in page order.

    Grouped by page because a chunk can cross a page break inside a section.
    A block without a bbox contributes nothing rather than a guessed rect; a
    chunk whose blocks all lack geometry gets [], and the reader shows its
    text without a highlight.
    """
    blocks = record["blocks"]
    by_page = {}
    for block_id in chunk["block_ids"]:
        if not 0 <= block_id < len(blocks):
            continue
        block = blocks[block_id]
        if not block["bbox"]:
            continue
        by_page.setdefault(block["page"], []).append(list(block["bbox"]))
    return [{"page": page, "rects": by_page[page]} for page in sorted(by_page)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -3`
Expected: both new tests pass, every existing test still passes.

- [ ] **Step 5: Write the failing test for the bundle writer**

Append to `lab/test_lab.py`, and add `import hashlib` to the imports at the top of the file if it is not already there:

```python
def test_write_bundle_writes_files_whose_hashes_match_the_manifest():
    record = ir_with_pages()
    entries = [{"filename": "Two Page Paper.pdf", "sha256": "0" * 64,
                "pages": 2, "chars_text_layer": 500, "scanned": False, "doi": None}]
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        corpus = d / "corpus"
        corpus.mkdir()
        (corpus / "Two Page Paper.pdf").write_bytes(b"%PDF-1.4 fake")
        out = d / "bundle"
        manifest_written = export.write_bundle([record], entries, out, corpus)

        assert manifest_written["counts"] == {"papers": 1, "chunks": 2}, manifest_written
        assert manifest_written["source_runner"] == "docling-default"
        for name, expected in manifest_written["files"].items():
            actual = hashlib.sha256((out / name).read_bytes()).hexdigest()
            assert actual == expected, f"{name} hash mismatch"
        assert (out / "pdfs" / "Two Page Paper.pdf").exists()
        chunks = json.loads((out / "chunks.json").read_text())
        assert chunks[0]["regions"][0]["page"] == 1
        assert chunks[1]["regions"] == []
        papers = json.loads((out / "papers.json").read_text())
        assert papers == [{"paper_id": "Two Page Paper", "filename": "Two Page Paper.pdf",
                           "pages": 2, "sha256": "0" * 64}], papers


def test_write_bundle_skips_a_pdf_that_is_not_in_the_corpus():
    record = ir_with_pages()
    entries = [{"filename": "Two Page Paper.pdf", "sha256": "0" * 64,
                "pages": 2, "chars_text_layer": 500, "scanned": False, "doi": None}]
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        corpus = d / "corpus"
        corpus.mkdir()                      # the PDF is deliberately absent
        out = d / "bundle"
        written = export.write_bundle([record], entries, out, corpus)
        assert written["missing_pdfs"] == ["Two Page Paper.pdf"], written
        assert not (out / "pdfs" / "Two Page Paper.pdf").exists()
        # the paper still ships: its text and regions are usable without the PDF
        assert written["counts"]["papers"] == 1
```

- [ ] **Step 6: Run to verify they fail**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -4`
Expected: FAIL with `AttributeError: module 'lab.export' has no attribute 'write_bundle'`.

- [ ] **Step 7: Implement `write_bundle`**

Append to `lab/export.py`:

```python
def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_bundle(records, entries, out_dir, corpus_dir, corpus_id=None, name=None):
    """Write manifest.json, papers.json, chunks.json and pdfs/ into out_dir.

    Returns the manifest dict. `vectors.bin` is Task 2's job and is added to
    the manifest by `lab.embed`, so a bundle written here is valid and simply
    has no semantic search.
    """
    out_dir = pathlib.Path(out_dir)
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)

    by_filename = {e["filename"]: e for e in entries}
    papers, chunks, missing = [], [], []
    for record in records:
        paper_id = record["paper_id"]
        entry = next((e for f, e in by_filename.items()
                      if pathlib.Path(f).stem == paper_id), None)
        if entry is None:
            continue
        papers.append({"paper_id": paper_id, "filename": entry["filename"],
                       "pages": entry["pages"], "sha256": entry["sha256"]})
        source = pathlib.Path(corpus_dir) / entry["filename"]
        if source.exists():
            shutil.copy2(source, out_dir / "pdfs" / entry["filename"])
        else:
            missing.append(entry["filename"])
        for chunk in record["chunks"]:
            chunks.append({
                "id": f"{paper_id}#{chunk['id']}",
                "paper_id": paper_id,
                "section": chunk["section"],
                "text": chunk["text"],
                "chars": chunk["chars"],
                "regions": chunk_regions(record, chunk),
            })

    files = {}
    for filename, payload in (("papers.json", papers), ("chunks.json", chunks)):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        (out_dir / filename).write_bytes(data)
        files[filename] = _sha256_bytes(data)

    first = records[0] if records else {}
    manifest = {
        "corpus_id": corpus_id or out_dir.name,
        "name": name or out_dir.name,
        "built_at": _now(),
        "source_runner": first.get("runner"),
        "runner_version": first.get("runner_version"),
        "embed_model": None,
        "dim": None,
        "counts": {"papers": len(papers), "chunks": len(chunks)},
        "files": files,
        "missing_pdfs": sorted(missing),
    }
    _write_manifest(out_dir, manifest)
    return manifest


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_manifest(out_dir, manifest):
    (pathlib.Path(out_dir) / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
```

- [ ] **Step 8: Run to verify they pass**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -3`
Expected: all tests pass.

- [ ] **Step 9: Wire the CLI subcommand**

In `lab/cli.py`, add after `cmd_import_baseline`:

```python
def cmd_export(args):
    """Write a reader bundle from one runner's results."""
    from lab import export, manifest

    results_path = RESULTS_DIR / f"{args.runner}.jsonl"
    if not results_path.exists():
        raise SystemExit(f"{results_path} not found — run: python -m lab run {args.runner}")
    records = [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]

    written = export.write_bundle(
        records, manifest.load(), pathlib.Path(args.out), manifest.corpus_dir(),
    )
    print(f"wrote {args.out}: {written['counts']['papers']} papers, "
          f"{written['counts']['chunks']} chunks")
    no_regions = sum(1 for c in json.loads((pathlib.Path(args.out) / "chunks.json").read_text())
                     if not c["regions"])
    print(f"  chunks without geometry: {no_regions}")
    if written["missing_pdfs"]:
        print(f"  PDFs not found in the corpus: {len(written['missing_pdfs'])}")

    if args.no_embed:
        print("  --no-embed: vectors.bin left alone, semantic search unavailable")
    return 0
```

and in `build_parser`, after the `import-baseline` block:

```python
    e = sub.add_parser("export", help="write a reader bundle from a runner's results")
    e.add_argument("runner")
    e.add_argument("--out", required=True, help="e.g. bundles/no-ragrets-47")
    e.add_argument("--no-embed", action="store_true", help="skip embeddings")
    e.set_defaults(func=cmd_export)
```

- [ ] **Step 10: Run it against the real corpus**

Run:
```bash
export NORAGRETS_CORPUS="$HOME/Desktop/Active Projects/No-RAGrets-Master/data/papers"
./.venv/bin/python -m lab export docling-default --out bundles/no-ragrets-47 --no-embed
```
Expected: `47 papers, 2800 chunks`, `chunks without geometry: 0`, no missing PDFs. If chunks-without-geometry is not 0, stop and report the count — the spec's acceptance criterion 2 says every chunk carries a region, and docling supplies a bbox for all 15,367 blocks.

- [ ] **Step 11: Gitignore the heavy parts and commit**

```bash
printf 'bundles/*/vectors.bin\nbundles/*/pdfs/\n' >> .gitignore
git add .gitignore lab/export.py lab/cli.py lab/test_lab.py
git commit -m "feat(export): bundle writer with build-time region resolution"
```

---

### Task 2: Embeddings and int8 vectors

Adds the only heavy dependency and the only step `--no-embed` skips. The quantization is measured, not asserted — if int8 costs real recall, the number says so.

**Files:**
- Create: `lab/embed.py`
- Modify: `lab/cli.py` (`cmd_export` calls it unless `--no-embed`), `requirements.txt`
- Test: `lab/test_lab.py` (append)

**Interfaces:**
- Consumes: `export.write_bundle`'s output directory and its `manifest.json`.
- Produces: `embed.embed_texts(texts, embedder=None) -> np.ndarray (n, 384) float32, rows L2-normalized`; `embed.quantize(vectors) -> (int8 array, float32 scales)`; `embed.dequantize(q, scales) -> float32 array`; `embed.write_vectors(out_dir, texts) -> dict` (the stats it printed). Task 7 reads the file format this task defines.

**`vectors.bin` format**, defined here and consumed by `web/src/retrieval/vectors.ts`: `n * 4` bytes of float32 scales, immediately followed by `n * dim` bytes of int8 values, row-major. Two contiguous blocks rather than interleaved rows, so the browser makes one `Float32Array` view and one `Int8Array` view with no stride arithmetic. `n` and `dim` come from `manifest.json`.

- [ ] **Step 1: Write the failing tests**

Append to `lab/test_lab.py`:

```python
from lab import embed


def test_embed_texts_normalizes_rows_even_if_the_embedder_does_not():
    import numpy as np
    # A deliberately unnormalized fake: cosine is only a dot product if rows are
    # unit length, and whether fastembed normalizes is not ours to assume.
    fake = lambda texts: [np.array([3.0, 4.0] + [0.0] * 382, dtype=np.float32) for _ in texts]
    out = embed.embed_texts(["a", "b"], embedder=fake)
    assert out.shape == (2, 384), out.shape
    assert abs(float(np.linalg.norm(out[0])) - 1.0) < 1e-6


def test_quantize_roundtrip_keeps_cosine_within_tolerance():
    import numpy as np
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(64, 384)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    q, scales = embed.quantize(vectors)
    assert q.dtype == np.int8 and q.shape == (64, 384)
    mean_error, worst_cos = embed.quantization_error(vectors, q, scales)
    assert mean_error < 0.001, mean_error
    assert worst_cos > 0.99, worst_cos


def test_write_vectors_round_trips_through_the_documented_layout():
    import numpy as np
    fake = lambda texts: [np.full(384, i + 1, dtype=np.float32) for i, _ in enumerate(texts)]
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "manifest.json").write_text(json.dumps({"counts": {"papers": 1, "chunks": 3}, "files": {}}))
        stats = embed.write_vectors(d, ["a", "b", "c"], embedder=fake)
        assert stats["dim"] == 384 and stats["count"] == 3

        manifest = json.loads((d / "manifest.json").read_text())
        assert manifest["embed_model"] == embed.MODEL
        assert manifest["dim"] == 384
        assert "vectors.bin" in manifest["files"]

        raw = (d / "vectors.bin").read_bytes()
        assert len(raw) == 3 * 4 + 3 * 384, len(raw)
        scales = np.frombuffer(raw, dtype=np.float32, count=3)
        q = np.frombuffer(raw, dtype=np.int8, offset=3 * 4).reshape(3, 384)
        back = embed.dequantize(q, scales)
        back /= np.linalg.norm(back, axis=1, keepdims=True)
        # all three fakes are constant vectors, so every row is the same direction
        assert float((back[0] * back[2]).sum()) > 0.999


def test_write_bundle_does_not_disturb_an_existing_vectors_file():
    record = ir_with_pages()
    entries = [{"filename": "Two Page Paper.pdf", "sha256": "0" * 64,
                "pages": 2, "chars_text_layer": 500, "scanned": False, "doi": None}]
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        corpus = d / "corpus"
        corpus.mkdir()
        out = d / "bundle"
        (out / "pdfs").mkdir(parents=True)
        (out / "vectors.bin").write_bytes(b"PRECIOUS")
        export.write_bundle([record], entries, out, corpus)
        assert (out / "vectors.bin").read_bytes() == b"PRECIOUS"
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -6`
Expected: FAIL naming `lab.embed`. The `write_bundle` vectors test should already PASS — it guards an invariant Task 1 happens to satisfy, and it fails loudly if someone later makes `write_bundle` clean its output directory.

- [ ] **Step 3: Install fastembed and record the resolved version**

Run:
```bash
./.venv/bin/pip install fastembed
./.venv/bin/pip show fastembed | head -2
```
Then add the resolved line to `requirements.txt` (e.g. `fastembed==<version>`), matching how the file already pins docling. fastembed is ONNX-based and must not pull torch; if the install log shows torch being downloaded, stop and report it — that is a different dependency decision than the one approved.

- [ ] **Step 4: Write `lab/embed.py`**

```python
"""Embed chunk text offline and write int8 vectors for the reader.

Kept out of export.py because this is the only step with a heavy dependency
and the only one `--no-embed` skips.

The model must match what the browser loads (Xenova/bge-small-en-v1.5), or
cosine scores compare two different vector spaces and look fine while being
meaningless. `manifest.json` records the model so the reader can refuse.
"""
import json
import pathlib

import numpy as np

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384


def embed_texts(texts, embedder=None):
    """float32 (n, DIM) with L2-normalized rows."""
    if embedder is None:
        from fastembed import TextEmbedding

        model = TextEmbedding(MODEL)
        embedder = lambda batch: list(model.embed(batch))      # noqa: E731
    raw = np.asarray(list(embedder(list(texts))), dtype=np.float32)
    if raw.ndim != 2 or raw.shape[1] != DIM:
        raise ValueError(f"expected (n, {DIM}) embeddings, got {raw.shape}")
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    # Normalize explicitly rather than trusting the embedder to have done it:
    # cosine is only a dot product on unit rows, and this is idempotent.
    return raw / norms


def quantize(vectors):
    """int8 values plus one float32 scale per row (symmetric max-abs)."""
    scales = np.abs(vectors).max(axis=1)
    scales[scales == 0] = 1.0
    q = np.round(vectors / scales[:, None] * 127.0).astype(np.int8)
    return q, scales.astype(np.float32)


def dequantize(q, scales):
    return q.astype(np.float32) * (np.asarray(scales, dtype=np.float32)[:, None] / 127.0)


def quantization_error(vectors, q, scales):
    """(mean 1 - cosine, worst cosine) between the originals and the round-trip."""
    back = dequantize(q, scales)
    back /= np.linalg.norm(back, axis=1, keepdims=True)
    cos = (vectors * back).sum(axis=1)
    return float(np.mean(1.0 - cos)), float(np.min(cos))


def write_vectors(out_dir, texts, embedder=None):
    """Write vectors.bin and record the model, dim and hash in manifest.json."""
    import hashlib

    out_dir = pathlib.Path(out_dir)
    vectors = embed_texts(texts, embedder=embedder)
    q, scales = quantize(vectors)
    mean_error, worst_cos = quantization_error(vectors, q, scales)

    payload = scales.tobytes() + q.tobytes()
    (out_dir / "vectors.bin").write_bytes(payload)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["embed_model"] = MODEL
    manifest["dim"] = DIM
    manifest.setdefault("files", {})["vectors.bin"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {"count": len(vectors), "dim": DIM, "bytes": len(payload),
            "mean_cosine_error": mean_error, "worst_cosine": worst_cos}
```

- [ ] **Step 5: Run to verify they pass**

Run: `./.venv/bin/python lab/test_lab.py 2>&1 | tail -3`
Expected: all tests pass.

- [ ] **Step 6: Call it from the CLI**

In `lab/cli.py`'s `cmd_export`, replace the `if args.no_embed:` block with:

```python
    if args.no_embed:
        print("  --no-embed: vectors.bin left alone, semantic search unavailable")
        return 0

    from lab import embed

    chunks = json.loads((pathlib.Path(args.out) / "chunks.json").read_text())
    stats = embed.write_vectors(pathlib.Path(args.out), [c["text"] for c in chunks])
    print(f"  embedded {stats['count']} chunks with {embed.MODEL} "
          f"({stats['bytes'] / 1e6:.2f} MB)")
    print(f"  int8 quantization: mean cosine error {stats['mean_cosine_error']:.5f}, "
          f"worst row cosine {stats['worst_cosine']:.4f}")
    return 0
```

- [ ] **Step 7: Build the real bundle**

Run:
```bash
export NORAGRETS_CORPUS="$HOME/Desktop/Active Projects/No-RAGrets-Master/data/papers"
./.venv/bin/python -m lab export docling-default --out bundles/no-ragrets-47
```
Expected: 47 papers, 2800 chunks, `vectors.bin` about 1.1 MB, mean cosine error well under 0.001. First run downloads the ONNX model (tens of MB) and takes a few minutes on CPU. **Report the two quantization numbers** — they are the measurement that justifies int8 over float32, and if the worst row cosine is below 0.99 the plan's compression choice needs revisiting before the frontend is built on it.

- [ ] **Step 8: Commit**

```bash
git add lab/embed.py lab/cli.py lab/test_lab.py requirements.txt
git commit -m "feat(export): offline embeddings with measured int8 quantization"
```

---

### Task 3: Prove docling's bboxes land on the rendered page

**Do this before any frontend work.** Every unit test in Tasks 5 and 8 can pass while every highlight sits in the wrong place, because a green rect-transform test does not know about page rotation, a cropbox offset, or a page-size mismatch. This task's output is an answer, not code we keep: three PNGs for a human to look at.

**Files:**
- Create: `tools/verify_highlights.py`

**Interfaces:**
- Consumes: `bundles/no-ragrets-47/chunks.json` from Task 1, `$NORAGRETS_CORPUS`.
- Produces: nothing other tasks import. A visual answer.

- [ ] **Step 1: Check that pdfplumber can rasterize in this venv**

Run:
```bash
./.venv/bin/python -c "
import pdfplumber, pathlib, os
p = sorted(pathlib.Path(os.environ['NORAGRETS_CORPUS']).glob('*.pdf'))[0]
with pdfplumber.open(p) as pdf:
    im = pdf.pages[0].to_image(resolution=72)
print('rasterizer ok', im.original.size)
"
```
Expected: `rasterizer ok (width, height)`. If it raises because no image backend is present, install `pypdfium2` into the venv and retry; if that also fails, say so and stop — the alternative is rendering through the browser, which is a different task.

pdfplumber's own coordinate space is `(x0, top, x1, bottom)` top-down in points, which is exactly the IR's convention. That is what makes this check meaningful: two independent libraries agreeing on where the text is.

- [ ] **Step 2: Write the script**

Create `tools/verify_highlights.py`:

```python
"""One-off check: do the bundle's chunk rectangles sit on the right text?

Not a test. A green rect-transform unit test cannot see a rotated page or a
cropbox offset; a human looking at three PNGs can. Run it once after a bundle
is built, and again if the geometry code ever changes.

    ./.venv/bin/python tools/verify_highlights.py bundles/no-ragrets-47
"""
import json
import pathlib
import sys

import pdfplumber

# One two-column paper (the report's own gutter-span example), one thesis with
# many tables, one ordinary article.
WANTED = ["A. Priyadarsini et al. 2023", "Adegbola thesis High Density Cultures",
          "Ahmadi & Lackner 2024"]
OUT_DIR = pathlib.Path("/tmp/noragrets-highlight-check")


def main(bundle_dir):
    bundle = pathlib.Path(bundle_dir)
    chunks = json.loads((bundle / "chunks.json").read_text())
    papers = {p["paper_id"]: p for p in json.loads((bundle / "papers.json").read_text())}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for paper_id in WANTED:
        paper = papers.get(paper_id)
        if paper is None:
            print(f"SKIP   {paper_id}: not in this bundle")
            continue
        # The longest chunk with geometry: the biggest target to judge by eye.
        candidates = [c for c in chunks if c["paper_id"] == paper_id and c["regions"]]
        if not candidates:
            print(f"SKIP   {paper_id}: no chunk carries geometry")
            continue
        chunk = max(candidates, key=lambda c: c["chars"])
        region = chunk["regions"][0]

        pdf_path = bundle / "pdfs" / paper["filename"]
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[region["page"] - 1]
            image = page.to_image(resolution=100)
            image.draw_rects(region["rects"], stroke="red", stroke_width=2)
            out = OUT_DIR / f"{paper_id.replace('/', '-')}-p{region['page']}.png"
            image.save(out)

        print(f"WROTE  {out}")
        print(f"       page {region['page']}, {len(region['rects'])} rect(s)")
        print(f"       chunk text starts: {chunk['text'][:90]!r}")
    print(f"\nOpen the PNGs and check the red rectangles sit on that text:\n  open {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "bundles/no-ragrets-47"))
```

- [ ] **Step 3: Run it**

Run: `./.venv/bin/python tools/verify_highlights.py bundles/no-ragrets-47`
Expected: three `WROTE` lines with page numbers, rect counts, and the first 90 characters of each chunk.

- [ ] **Step 4: STOP and get a human verdict**

Show Soren the three PNGs and the quoted chunk text. The question is narrow: **does each red rectangle sit on the text quoted beneath it?**

- All three clean → the `[x0, top, x1, bottom]` contract holds, Tasks 5 and 8 can assume no flip and no offset.
- Rectangles vertically mirrored → the flip in `lab/runners.py:300` is wrong for these pages. Fix it there, in the one place, and rebuild the bundle. Do not compensate in the frontend.
- Rectangles offset by a constant → a cropbox or mediabox origin is being ignored. That is a `lab/runners.py` fix too, and it needs the page's cropbox in the IR.

Do not start Task 4 until this is answered.

- [ ] **Step 5: Commit the script**

```bash
git add tools/verify_highlights.py
git commit -m "tools: one-off visual check that chunk rects land on the right text"
```

---

### Task 4: Web scaffold and the bundle loader

The loader is where the `embed_model` guard lives, so it is the first frontend code written and the only place that decides whether semantic search is available.

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/index.css`, `web/src/bundle.ts`
- Test: `web/src/bundle.test.ts`

**Interfaces:**
- Consumes: the bundle format defined in Tasks 1 and 2.
- Produces: the types `Rect`, `Region`, `Chunk`, `Paper`, `Manifest`, `Bundle`; the constants `QUERY_MODEL` and `MODEL_PAIRS`; `loadBundle(baseUrl, opts?) -> Promise<Bundle>`. Every later frontend task imports from here.

- [ ] **Step 1: Scaffold the app**

Run from the repo root:
```bash
npm create vite@latest web -- --template react-ts
cd web && npm install
npm i react-router-dom react-pdf @huggingface/transformers
npm i -D tailwindcss @tailwindcss/vite vitest
cd ..
```

Set `web/vite.config.ts` to:

```ts
// vitest/config, not vite: the `test` key below is Vitest's and vite's types reject it.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // GitHub Pages serves this repo at /No-RAGrets-v2/, so asset URLs need the prefix.
  base: "/No-RAGrets-v2/",
  plugins: [react(), tailwindcss()],
  test: { environment: "node" },
});
```

Replace `web/src/index.css` with `@import "tailwindcss";` and add `"test": "vitest run"` to `web/package.json`'s scripts.

- [ ] **Step 2: Write the failing loader tests**

Create `web/src/bundle.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { loadBundle, QUERY_MODEL } from "./bundle";

function fakeFetch(files: Record<string, unknown | ArrayBuffer>) {
  return async (url: string) => {
    const name = url.split("/").pop()!;
    if (!(name in files)) return new Response(null, { status: 404 });
    const value = files[name];
    if (value instanceof ArrayBuffer) return new Response(value, { status: 200 });
    return new Response(JSON.stringify(value), { status: 200 });
  };
}

const manifest = {
  corpus_id: "fix", name: "Fixture", built_at: "2026-10-01T00:00:00+00:00",
  source_runner: "docling-default", runner_version: "test",
  embed_model: "BAAI/bge-small-en-v1.5", dim: 4,
  counts: { papers: 1, chunks: 2 }, files: {}, missing_pdfs: [],
};
const papers = [{ paper_id: "P", filename: "P.pdf", pages: 2, sha256: "0".repeat(64) }];
const chunks = [
  { id: "P#0", paper_id: "P", section: "Results", text: "methane yield rose", chars: 18,
    regions: [{ page: 1, rects: [[10, 20, 90, 40]] }] },
  { id: "P#1", paper_id: "P", section: "Results", text: "no geometry here", chars: 16, regions: [] },
];

function vectorsBin(): ArrayBuffer {
  // 2 rows x dim 4: scales block (float32) then int8 block, per lab/embed.py
  const buffer = new ArrayBuffer(2 * 4 + 2 * 4);
  new Float32Array(buffer, 0, 2).set([1, 1]);
  new Int8Array(buffer, 8, 8).set([127, 0, 0, 0, 0, 127, 0, 0]);
  return buffer;
}

describe("loadBundle", () => {
  it("loads papers, chunks and vectors and reports semantic as available", async () => {
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": manifest, "papers.json": papers,
                         "chunks.json": chunks, "vectors.bin": vectorsBin() }),
    });
    expect(bundle.papers).toHaveLength(1);
    expect(bundle.chunks[0].regions[0].page).toBe(1);
    expect(bundle.semantic).toEqual({ available: true, model: QUERY_MODEL });
    expect(bundle.vectors).toHaveLength(2 * 4);
  });

  it("refuses semantic search when the manifest model is not the one the app loads", async () => {
    const wrong = { ...manifest, embed_model: "intfloat/e5-base-v2" };
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": wrong, "papers.json": papers,
                         "chunks.json": chunks, "vectors.bin": vectorsBin() }),
    });
    expect(bundle.semantic.available).toBe(false);
    expect(bundle.semantic.reason).toBe("embed-model-mismatch");
    expect(bundle.vectors).toBeNull();
    expect(bundle.chunks).toHaveLength(2);   // reading and lexical search survive
  });

  it("falls back to lexical when vectors.bin is absent", async () => {
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": { ...manifest, embed_model: null, dim: null },
                         "papers.json": papers, "chunks.json": chunks }),
    });
    expect(bundle.semantic).toEqual({ available: false, reason: "no-vectors" });
  });

  it("throws when the bundle itself cannot be read", async () => {
    await expect(loadBundle("/bundles/fix", { fetch: fakeFetch({}) })).rejects.toThrow(/manifest/);
  });
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `Cannot find module './bundle'`.

- [ ] **Step 4: Write `web/src/bundle.ts`**

```ts
/** The bundle contract. Written by `python -m lab export`; read only here. */

export type Rect = [number, number, number, number];   // x0, top, x1, bottom, PDF points, top-down
export type Region = { page: number; rects: Rect[] };
export type Chunk = {
  id: string; paper_id: string; section: string | null;
  text: string; chars: number; regions: Region[];
};
export type Paper = { paper_id: string; filename: string; pages: number; sha256: string };
export type Manifest = {
  corpus_id: string; name: string; built_at: string;
  source_runner: string; runner_version: string;
  embed_model: string | null; dim: number | null;
  counts: { papers: number; chunks: number };
  files: Record<string, string>; missing_pdfs: string[];
};
export type SemanticStatus =
  | { available: true; model: string }
  | { available: false; reason: "no-vectors" | "embed-model-mismatch" };
export type Bundle = {
  baseUrl: string; manifest: Manifest; papers: Paper[]; chunks: Chunk[];
  /** Dequantized, L2-normalized, row-major count x dim. Null when unavailable. */
  vectors: Float32Array | null;
  semantic: SemanticStatus;
};

/** The browser-side half of the pair in lab/embed.py. Same weights. */
export const QUERY_MODEL = "Xenova/bge-small-en-v1.5";
export const MODEL_PAIRS: Record<string, string> = {
  "BAAI/bge-small-en-v1.5": QUERY_MODEL,
};

export async function loadBundle(
  baseUrl: string,
  opts: { fetch?: typeof fetch } = {},
): Promise<Bundle> {
  const get = opts.fetch ?? fetch;

  const read = async (name: string) => {
    const response = await get(`${baseUrl}/${name}`);
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    return response;
  };

  const manifest = (await (await read("manifest.json")).json()) as Manifest;
  const papers = (await (await read("papers.json")).json()) as Paper[];
  const chunks = (await (await read("chunks.json")).json()) as Chunk[];

  // A mismatch here produces cosine scores across two different vector spaces:
  // plausible-looking numbers that mean nothing. Refuse instead of warning.
  if (!manifest.embed_model) {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "no-vectors" } };
  }
  if (MODEL_PAIRS[manifest.embed_model] !== QUERY_MODEL) {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "embed-model-mismatch" } };
  }

  const dim = manifest.dim ?? 0;
  const count = manifest.counts.chunks;
  let vectors: Float32Array | null = null;
  try {
    const buffer = await (await read("vectors.bin")).arrayBuffer();
    const { dequantize } = await import("./retrieval/vectors");
    vectors = dequantize(buffer, count, dim);
  } catch {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "no-vectors" } };
  }
  return { baseUrl, manifest, papers, chunks, vectors,
           semantic: { available: true, model: QUERY_MODEL } };
}
```

- [ ] **Step 5: Write the dequantizer the loader imports**

Create `web/src/retrieval/vectors.ts`:

```ts
/** Reads the layout lab/embed.py writes: float32 scales block, then int8 block. */
export function dequantize(buffer: ArrayBuffer, count: number, dim: number): Float32Array {
  const expected = count * 4 + count * dim;
  if (buffer.byteLength !== expected) {
    throw new Error(`vectors.bin is ${buffer.byteLength} bytes, expected ${expected}`);
  }
  const scales = new Float32Array(buffer, 0, count);
  const quantized = new Int8Array(buffer, count * 4, count * dim);
  const out = new Float32Array(count * dim);
  for (let row = 0; row < count; row++) {
    const factor = scales[row] / 127;
    let sum = 0;
    for (let i = 0; i < dim; i++) {
      const value = quantized[row * dim + i] * factor;
      out[row * dim + i] = value;
      sum += value * value;
    }
    // Re-normalize after dequantizing so cosine stays a plain dot product.
    const norm = Math.sqrt(sum) || 1;
    for (let i = 0; i < dim; i++) out[row * dim + i] /= norm;
  }
  return out;
}
```

- [ ] **Step 6: Run to verify they pass**

Run: `cd web && npm test`
Expected: 4 passing tests.

- [ ] **Step 7: Commit**

```bash
git add web/ && git commit -m "feat(web): scaffold plus bundle loader with an enforced embed-model guard"
```

---

### Task 5: Geometry and the highlight overlay

**Files:**
- Create: `web/src/geometry.ts`, `web/src/components/Highlight.tsx`
- Test: `web/src/geometry.test.ts`

**Interfaces:**
- Consumes: `Rect` from `./bundle`.
- Produces: `pageScale(renderedWidth, originalWidthInPoints) -> number`; `rectToStyle(rect, scale) -> {left, top, width, height}` (all numbers, CSS pixels); `<Highlight rects={Rect[]} scale={number} />`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/geometry.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { pageScale, rectToStyle } from "./geometry";

describe("pageScale", () => {
  it("is the ratio of rendered pixels to PDF points", () => {
    // react-pdf reports width in CSS pixels and originalWidth in points.
    expect(pageScale(1224, 612)).toBe(2);
    expect(pageScale(612, 612)).toBe(1);
  });

  it("falls back to 1 rather than dividing by zero", () => {
    expect(pageScale(800, 0)).toBe(1);
  });
});

describe("rectToStyle", () => {
  it("scales a top-down rect with no flip", () => {
    expect(rectToStyle([10, 20, 90, 50], 2)).toEqual({ left: 20, top: 40, width: 160, height: 60 });
  });

  it("never returns a negative size for an inverted rect", () => {
    const style = rectToStyle([90, 50, 10, 20], 1);
    expect(style.width).toBeGreaterThanOrEqual(0);
    expect(style.height).toBeGreaterThanOrEqual(0);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `Cannot find module './geometry'`.

- [ ] **Step 3: Write `web/src/geometry.ts`**

```ts
import type { Rect } from "./bundle";

/** Rendered CSS pixels per PDF point.
 *
 * Derived from what react-pdf reports rather than assumed from a scale prop or
 * a 72-vs-96 dpi guess: `width` is the rendered size, `originalWidth` is points.
 * v1 hardcoded scales in two places and they disagreed.
 */
export function pageScale(renderedWidth: number, originalWidthInPoints: number): number {
  if (!originalWidthInPoints) return 1;
  return renderedWidth / originalWidthInPoints;
}

/** A top-down [x0, top, x1, bottom] rect in points to CSS pixel offsets.
 *
 * No coordinate flip: lab/runners.py already converted docling's bottom-left
 * origin once, offline. If highlights ever come out mirrored, fix it there.
 */
export function rectToStyle([x0, top, x1, bottom]: Rect, scale: number) {
  return {
    left: Math.min(x0, x1) * scale,
    top: Math.min(top, bottom) * scale,
    width: Math.abs(x1 - x0) * scale,
    height: Math.abs(bottom - top) * scale,
  };
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test`
Expected: all geometry tests pass.

- [ ] **Step 5: Write the overlay component**

Create `web/src/components/Highlight.tsx`:

```tsx
import type { Rect } from "../bundle";
import { rectToStyle } from "../geometry";

/** Absolutely-positioned divs over a rendered page. Divs rather than a canvas:
 *  they take CSS transitions, survive a re-render, and need no redraw loop. */
export function Highlight({ rects, scale }: { rects: Rect[]; scale: number }) {
  return (
    <>
      {rects.map((rect, i) => (
        <div
          key={i}
          aria-hidden
          className="absolute bg-yellow-300/40 ring-2 ring-yellow-500 rounded-sm"
          style={rectToStyle(rect, scale)}
        />
      ))}
    </>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add web/src/geometry.ts web/src/geometry.test.ts web/src/components/Highlight.tsx
git commit -m "feat(web): rect geometry derived from the rendered page, plus the overlay"
```

---

### Task 6: Lexical search (BM25)

The baseline semantic search has to visibly beat. Shipped, not hidden behind a flag.

**Files:**
- Create: `web/src/retrieval/bm25.ts`
- Test: `web/src/retrieval/bm25.test.ts`

**Interfaces:**
- Consumes: `Chunk` from `../bundle`.
- Produces: `buildIndex(chunks) -> Bm25Index`; `rank(index, query, k) -> {chunk_id, score}[]`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/retrieval/bm25.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildIndex, rank } from "./bm25";
import type { Chunk } from "../bundle";

const chunk = (id: string, text: string): Chunk =>
  ({ id, paper_id: "P", section: null, text, chars: text.length, regions: [] });

const chunks = [
  chunk("a", "methane oxidation by methanotrophs in a bioreactor"),
  chunk("b", "the bioreactor was stirred at 300 rpm"),
  chunk("c", "nitrogen fixation in soil samples"),
];

describe("bm25", () => {
  it("ranks the chunk that repeats the query term first", () => {
    const hits = rank(buildIndex(chunks), "methane methanotrophs", 3);
    expect(hits[0].chunk_id).toBe("a");
    expect(hits[0].score).toBeGreaterThan(0);
  });

  it("gives a term that appears in every document almost no weight", () => {
    const everywhere = [chunk("a", "bioreactor one"), chunk("b", "bioreactor two")];
    const hits = rank(buildIndex(everywhere), "bioreactor", 2);
    expect(hits.every((h) => h.score <= 0.0001)).toBe(true);
  });

  it("returns nothing for an empty or unmatched query", () => {
    const index = buildIndex(chunks);
    expect(rank(index, "   ", 5)).toEqual([]);
    expect(rank(index, "zebra", 5)).toEqual([]);
  });

  it("respects k", () => {
    expect(rank(buildIndex(chunks), "bioreactor", 1)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `Cannot find module './bm25'`.

- [ ] **Step 3: Write `web/src/retrieval/bm25.ts`**

```ts
import type { Chunk } from "../bundle";

const K1 = 1.2;
const B = 0.75;

export type Bm25Index = {
  ids: string[];
  lengths: number[];
  avgLength: number;
  /** term -> [docIndex, termFrequency][] */
  postings: Map<string, [number, number][]>;
};

export function tokenize(text: string): string[] {
  return text.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 1);
}

export function buildIndex(chunks: Chunk[]): Bm25Index {
  const ids: string[] = [];
  const lengths: number[] = [];
  const postings = new Map<string, [number, number][]>();

  chunks.forEach((chunk, doc) => {
    const tokens = tokenize(chunk.text);
    ids.push(chunk.id);
    lengths.push(tokens.length);
    const counts = new Map<string, number>();
    for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
    for (const [token, frequency] of counts) {
      const list = postings.get(token) ?? [];
      list.push([doc, frequency]);
      postings.set(token, list);
    }
  });

  const total = lengths.reduce((a, b) => a + b, 0);
  return { ids, lengths, avgLength: total / (lengths.length || 1), postings };
}

export function rank(index: Bm25Index, query: string, k: number) {
  const terms = tokenize(query);
  if (terms.length === 0) return [];
  const docCount = index.ids.length;
  const scores = new Map<number, number>();

  for (const term of terms) {
    const postings = index.postings.get(term);
    if (!postings) continue;
    // Robertson/Sparck-Jones idf: a term in every document scores ~0, which is
    // the behaviour the test pins.
    const idf = Math.log(1 + (docCount - postings.length + 0.5) / (postings.length + 0.5));
    for (const [doc, frequency] of postings) {
      const norm = frequency + K1 * (1 - B + (B * index.lengths[doc]) / index.avgLength);
      scores.set(doc, (scores.get(doc) ?? 0) + (idf * frequency * (K1 + 1)) / norm);
    }
  }

  return [...scores.entries()]
    .filter(([, score]) => score > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([doc, score]) => ({ chunk_id: index.ids[doc], score }));
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test`
Expected: 4 bm25 tests pass. If the all-documents test fails because idf is slightly above the threshold, do not loosen the threshold — check the formula.

- [ ] **Step 5: Commit**

```bash
git add web/src/retrieval/bm25.ts web/src/retrieval/bm25.test.ts
git commit -m "feat(web): BM25 lexical search as the baseline for semantic to beat"
```

---

### Task 7: Semantic search, and proving both sides share one vector space

The parity check here is the load-bearing one. `fastembed` pools bge with the CLS token; transformers.js defaults to mean pooling. Get that wrong and every score is quietly meaningless — the exact failure the `embed_model` guard cannot catch, because the model id matches.

**Files:**
- Create: `web/src/retrieval/embedder.ts`, `web/src/retrieval/index.ts`, `web/test-fixtures/parity.json`
- Test: `web/src/retrieval/vectors.test.ts`, `web/src/retrieval/parity.test.ts`

**Interfaces:**
- Consumes: `dequantize` (Task 4), `rank`/`buildIndex` (Task 6), `Bundle` (Task 4).
- Produces: `embedQuery(text) -> Promise<Float32Array>`; `cosineTopK(query, matrix, count, dim, k) -> {index, score}[]`; `search(bundle, query, {mode, k}) -> Promise<Hit[]>` where `Hit = {chunk_id, score, mode}`.

- [ ] **Step 1: Write the failing cosine tests**

Create `web/src/retrieval/vectors.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { cosineTopK, dequantize } from "./vectors";

describe("cosineTopK", () => {
  it("ranks the identical row first and the opposite row last", () => {
    const dim = 2;
    const matrix = new Float32Array([1, 0, 0.7071, 0.7071, -1, 0]);
    const hits = cosineTopK(new Float32Array([1, 0]), matrix, 3, dim, 3);
    expect(hits.map((h) => h.index)).toEqual([0, 1, 2]);
    expect(hits[0].score).toBeCloseTo(1, 5);
    expect(hits[2].score).toBeCloseTo(-1, 5);
  });

  it("respects k", () => {
    const matrix = new Float32Array([1, 0, 0, 1]);
    expect(cosineTopK(new Float32Array([1, 0]), matrix, 2, 2, 1)).toHaveLength(1);
  });
});

describe("dequantize", () => {
  it("rejects a file whose length disagrees with the manifest", () => {
    expect(() => dequantize(new ArrayBuffer(10), 2, 4)).toThrow(/expected/);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `cosineTopK` is not exported.

- [ ] **Step 3: Add `cosineTopK` to `web/src/retrieval/vectors.ts`**

```ts
/** Top k rows by dot product. Rows and query are unit length, so dot == cosine. */
export function cosineTopK(
  query: Float32Array, matrix: Float32Array, count: number, dim: number, k: number,
) {
  const scored: { index: number; score: number }[] = [];
  for (let row = 0; row < count; row++) {
    let dot = 0;
    const offset = row * dim;
    for (let i = 0; i < dim; i++) dot += query[i] * matrix[offset + i];
    scored.push({ index: row, score: dot });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test`
Expected: all vectors tests pass.

- [ ] **Step 5: Write the lazy query embedder**

Create `web/src/retrieval/embedder.ts`:

```ts
import { QUERY_MODEL } from "../bundle";

let pending: Promise<unknown> | null = null;

/** Embeds one query, loading the model on first use (about 33MB, then cached).
 *
 * `pooling: "cls"` is NOT the library default — it is what bge models use, and
 * what fastembed does on the Python side. Mean pooling here would produce
 * vectors in a different space from the bundle's while the model id still
 * matched, so no guard would catch it. The parity test is what pins this.
 */
export async function embedQuery(text: string): Promise<Float32Array> {
  if (!pending) {
    pending = import("@huggingface/transformers").then(({ pipeline }) =>
      pipeline("feature-extraction", QUERY_MODEL, { dtype: "q8" }),
    );
  }
  const extractor = (await pending) as (
    input: string, options: { pooling: "cls"; normalize: boolean },
  ) => Promise<{ data: Float32Array }>;
  const output = await extractor(text, { pooling: "cls", normalize: true });
  return new Float32Array(output.data);
}
```

- [ ] **Step 6: Generate the parity fixture from the Python side**

Run from the repo root:
```bash
./.venv/bin/python -c "
import json
from lab import embed
texts = ['methane oxidation by methanotrophs',
         'the reactor was stirred at 300 rpm',
         'nitrogen fixation in soil samples']
vectors = embed.embed_texts(texts)
json.dump({'model': embed.MODEL, 'texts': texts, 'vectors': vectors.tolist()},
          open('web/test-fixtures/parity.json', 'w'))
print('wrote web/test-fixtures/parity.json')
"
```
Create the directory first if needed. This fixture is the Python half of the contract and is committed.

- [ ] **Step 7: Write the parity test**

Create `web/src/retrieval/parity.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import parity from "../../test-fixtures/parity.json";
import { embedQuery } from "./embedder";

// Downloads the ONNX model on first run (about 33MB, then cached on disk).
// SKIP_PARITY=1 skips it; do not skip it after touching the embedder.
const run = process.env.SKIP_PARITY ? it.skip : it;

describe("python/browser embedding parity", () => {
  run("agrees with fastembed on the same sentences", async () => {
    for (let i = 0; i < parity.texts.length; i++) {
      const mine = await embedQuery(parity.texts[i]);
      const theirs = parity.vectors[i] as number[];
      expect(mine).toHaveLength(theirs.length);
      let dot = 0;
      for (let j = 0; j < theirs.length; j++) dot += mine[j] * theirs[j];
      // Same weights, same pooling, both normalized: cosine should be ~1.
      // Below 0.99 means the pooling or the model pair is wrong.
      expect(dot).toBeGreaterThan(0.99);
    }
  }, 180_000);
});
```

- [ ] **Step 8: Run the parity test and act on the result**

Run: `cd web && npx vitest run src/retrieval/parity.test.ts`
Expected: PASS with cosine above 0.99.

If it fails near 0.9x, the pooling is the suspect: try `pooling: "mean"` and re-run. **Whichever one passes, make the Python and browser sides agree and write the finding into the plan's task notes** — this is the one mismatch no runtime guard can see. If neither passes, stop and report: the model pair may not be weight-identical, which invalidates the bundle format's assumption.

- [ ] **Step 9: Write the single search entry point**

Create `web/src/retrieval/index.ts`:

```ts
import type { Bundle } from "../bundle";
import { buildIndex, rank, type Bm25Index } from "./bm25";
import { cosineTopK } from "./vectors";
import { embedQuery } from "./embedder";

export type Mode = "semantic" | "lexical";
export type Hit = { chunk_id: string; score: number; mode: Mode };

const indexes = new WeakMap<Bundle, Bm25Index>();

function lexicalIndex(bundle: Bundle): Bm25Index {
  let index = indexes.get(bundle);
  if (!index) {
    index = buildIndex(bundle.chunks);
    indexes.set(bundle, index);
  }
  return index;
}

/** One mode per call. There is deliberately no blended mode: a merged score
 *  would be the composite number this project refuses to ship. */
export async function search(
  bundle: Bundle, query: string, { mode, k = 10 }: { mode: Mode; k?: number },
): Promise<Hit[]> {
  if (!query.trim()) return [];

  if (mode === "lexical") {
    return rank(lexicalIndex(bundle), query, k).map((hit) => ({ ...hit, mode }));
  }

  if (!bundle.semantic.available || !bundle.vectors || !bundle.manifest.dim) {
    throw new Error(`semantic search unavailable: ${
      bundle.semantic.available ? "no vectors" : bundle.semantic.reason}`);
  }
  const query_vector = await embedQuery(query);
  const hits = cosineTopK(
    query_vector, bundle.vectors, bundle.manifest.counts.chunks, bundle.manifest.dim, k,
  );
  return hits.map(({ index, score }) => ({ chunk_id: bundle.chunks[index].id, score, mode }));
}
```

- [ ] **Step 10: Run the whole suite and commit**

Run: `cd web && npm test`
Expected: every test passes, parity included.

```bash
git add web/src/retrieval web/test-fixtures/parity.json
git commit -m "feat(web): semantic search with a pinned python/browser embedding parity test"
```

---

### Task 8: Paper list and the reader

**Files:**
- Create: `web/src/components/PaperList.tsx`, `web/src/components/Reader.tsx`, `web/src/pdf-worker.ts`
- Modify: `web/src/App.tsx`, `web/src/main.tsx`

**Interfaces:**
- Consumes: `Bundle`, `Paper`, `Chunk` (Task 4), `pageScale` (Task 5), `Highlight` (Task 5).
- Produces: `<PaperList bundle={Bundle} />`, `<Reader bundle={Bundle} />`. Task 9 navigates to `#/paper/:paperId?chunk=<chunk id>`.

- [ ] **Step 1: Confirm how this react-pdf version wants its worker**

Run: `cd web && node -e "console.log(require('react-pdf/package.json').version)"` and read `node_modules/react-pdf/README.md` for the worker setup section.

The import path for the worker moved between major versions, so use what the installed version documents rather than what this plan guesses. The shape is:

```ts
// web/src/pdf-worker.ts — imported once, from main.tsx
import { pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
```

If the README names a different file, change the import and note it. A wrong worker path fails at runtime with "Setting up fake worker failed", not at build time.

- [ ] **Step 2: Routes, with a hash router on purpose**

Replace `web/src/App.tsx`:

```tsx
import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { loadBundle, type Bundle } from "./bundle";
import { PaperList } from "./components/PaperList";
import { Reader } from "./components/Reader";

// A hash router, not a browser router: GitHub Pages has no server-side rewrite,
// so /paper/x would 404 on a reload. #/paper/x always resolves to index.html.
const BUNDLE_URL = `${import.meta.env.BASE_URL}bundles/no-ragrets-47`;

export default function App() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadBundle(BUNDLE_URL).then(setBundle, (e) => setError(String(e)));
  }, []);

  if (error) return <p className="p-6 text-red-700">Could not load the corpus: {error}</p>;
  if (!bundle) return <p className="p-6">Loading the corpus…</p>;

  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<PaperList bundle={bundle} />} />
        <Route path="/paper/:paperId" element={<Reader bundle={bundle} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
```

In `web/src/main.tsx`, add `import "./pdf-worker";` above the render call.

- [ ] **Step 3: The paper list**

Create `web/src/components/PaperList.tsx`:

```tsx
import { Link } from "react-router-dom";
import type { Bundle } from "../bundle";
import { SearchPanel } from "./SearchPanel";

export function PaperList({ bundle }: { bundle: Bundle }) {
  const counts = new Map<string, number>();
  for (const chunk of bundle.chunks) {
    counts.set(chunk.paper_id, (counts.get(chunk.paper_id) ?? 0) + 1);
  }
  const missing = new Set(bundle.manifest.missing_pdfs);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="text-2xl font-semibold">{bundle.manifest.name}</h1>
      <p className="mt-1 text-sm text-neutral-600">
        {bundle.manifest.counts.papers} papers, {bundle.manifest.counts.chunks} chunks,
        extracted with {bundle.manifest.source_runner} ({bundle.manifest.runner_version}).
      </p>

      <SearchPanel bundle={bundle} />

      <ul className="mt-6 divide-y">
        {bundle.papers.map((paper) => (
          <li key={paper.paper_id} className="py-2">
            <Link className="text-blue-700 hover:underline" to={`/paper/${encodeURIComponent(paper.paper_id)}`}>
              {paper.paper_id}
            </Link>
            <span className="ml-2 text-sm text-neutral-500">
              {paper.pages} pages · {counts.get(paper.paper_id) ?? 0} chunks
              {missing.has(paper.filename) ? " · PDF not in this bundle" : ""}
            </span>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

- [ ] **Step 4: The reader**

Create `web/src/components/Reader.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { Document, Page } from "react-pdf";
import type { Bundle } from "../bundle";
import { pageScale } from "../geometry";
import { Highlight } from "./Highlight";
import { AskBox } from "./AskBox";

export function Reader({ bundle }: { bundle: Bundle }) {
  const { paperId = "" } = useParams();
  const [params] = useSearchParams();
  const paper = bundle.papers.find((p) => p.paper_id === decodeURIComponent(paperId));
  const chunks = useMemo(
    () => bundle.chunks.filter((c) => c.paper_id === decodeURIComponent(paperId)),
    [bundle, paperId],
  );
  const focused = chunks.find((c) => c.id === params.get("chunk")) ?? null;
  const firstRegion = focused?.regions[0] ?? null;

  // One page at a time, not a continuous scroll: a 300-page thesis renders in
  // this corpus and rendering every page of it is how a reader locks up.
  const [pageNumber, setPageNumber] = useState(firstRegion?.page ?? 1);
  const [scale, setScale] = useState(1);

  if (!paper) return <p className="p-6">No paper called {decodeURIComponent(paperId)} in this bundle.</p>;

  const pdfMissing = bundle.manifest.missing_pdfs.includes(paper.filename);
  const rects = firstRegion && firstRegion.page === pageNumber ? firstRegion.rects : [];

  return (
    <main className="mx-auto max-w-6xl p-6">
      <Link to="/" className="text-sm text-blue-700 hover:underline">← all papers</Link>
      <h1 className="mt-2 text-xl font-semibold">{paper.paper_id}</h1>

      <div className="mt-4 grid gap-6 md:grid-cols-[2fr_1fr]">
        <div>
          {pdfMissing ? (
            <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
              PDF not in this bundle. The chunk text beside this is what the model sees,
              so citations still resolve — only the page image is missing.
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm">
                <button className="rounded border px-2" onClick={() => setPageNumber((n) => Math.max(1, n - 1))}>
                  prev
                </button>
                <span>page {pageNumber} of {paper.pages}</span>
                <button
                  className="rounded border px-2"
                  onClick={() => setPageNumber((n) => Math.min(paper.pages, n + 1))}
                >
                  next
                </button>
              </div>
              <div className="relative mt-2 inline-block">
                <Document file={`${bundle.baseUrl}/pdfs/${encodeURIComponent(paper.filename)}`}>
                  <Page
                    pageNumber={pageNumber}
                    // Our highlights are our own divs, so neither layer is needed;
                    // turning them off also silences react-pdf's missing-CSS warning.
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                    onLoadSuccess={({ width, originalWidth }) =>
                      setScale(pageScale(width, originalWidth))
                    }
                  />
                </Document>
                <Highlight rects={rects} scale={scale} />
              </div>
            </>
          )}
        </div>

        <aside>
          {focused && (
            <section className="rounded border p-3">
              <h2 className="text-sm font-semibold">Cited passage</h2>
              <p className="mt-1 text-xs text-neutral-500">
                {focused.section ?? "no section"} · page {firstRegion?.page ?? "?"}
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm">{focused.text}</p>
            </section>
          )}
          <AskBox bundle={bundle} scope={{ kind: "paper", paperId: paper.paper_id }} />
        </aside>
      </div>
    </main>
  );
}
```

- [ ] **Step 5: Build and look at it**

Run: `cd web && npm run build && npm run dev`
Then open the dev URL, click into `A. Priyadarsini et al. 2023`, and page through. The PDF must render and the page controls must work. `SearchPanel` and `AskBox` do not exist yet, so comment their imports and usages out for this step only, and uncomment them in Tasks 9 and 11.

- [ ] **Step 6: Commit**

```bash
git add web/src && git commit -m "feat(web): paper list and single-page reader with the highlight overlay"
```

---

### Task 9: The search panel, two rankings side by side

**Files:**
- Create: `web/src/components/SearchPanel.tsx`, `web/src/compare.ts`
- Test: `web/src/compare.test.ts`

**Interfaces:**
- Consumes: `search`, `Hit`, `Mode` (Task 7); `Bundle`, `Chunk` (Task 4).
- Produces: `compareRankings(semantic, lexical) -> {overlap: number, onlySemantic: string[], onlyLexical: string[]}`; `<SearchPanel bundle={Bundle} />`.

- [ ] **Step 1: Write the failing comparison tests**

Create `web/src/compare.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { compareRankings } from "./compare";
import type { Hit } from "./retrieval";

const hit = (id: string, score: number, mode: Hit["mode"]): Hit =>
  ({ chunk_id: id, score, mode });

describe("compareRankings", () => {
  it("reports overlap and each mode's exclusives without merging scores", () => {
    const semantic = [hit("a", 0.9, "semantic"), hit("b", 0.8, "semantic")];
    const lexical = [hit("b", 4.1, "lexical"), hit("c", 2.0, "lexical")];
    expect(compareRankings(semantic, lexical)).toEqual({
      overlap: 1, onlySemantic: ["a"], onlyLexical: ["c"],
    });
  });

  it("handles one side being empty", () => {
    expect(compareRankings([], [hit("a", 1, "lexical")])).toEqual({
      overlap: 0, onlySemantic: [], onlyLexical: ["a"],
    });
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `Cannot find module './compare'`.

- [ ] **Step 3: Write `web/src/compare.ts`**

```ts
import type { Hit } from "./retrieval";

/** How the two rankings differ, as counts and ids — never as a merged score.
 *  This is the number that answers "do the embeddings earn their 1.1MB". */
export function compareRankings(semantic: Hit[], lexical: Hit[]) {
  const semanticIds = semantic.map((h) => h.chunk_id);
  const lexicalIds = lexical.map((h) => h.chunk_id);
  const lexicalSet = new Set(lexicalIds);
  const semanticSet = new Set(semanticIds);
  return {
    overlap: semanticIds.filter((id) => lexicalSet.has(id)).length,
    onlySemantic: semanticIds.filter((id) => !lexicalSet.has(id)),
    onlyLexical: lexicalIds.filter((id) => !semanticSet.has(id)),
  };
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test`
Expected: both comparison tests pass.

- [ ] **Step 5: Write the panel**

Create `web/src/components/SearchPanel.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Bundle, Chunk } from "../bundle";
import { search, type Hit } from "../retrieval";
import { compareRankings } from "../compare";

function Results({ title, hits, byId, note }: {
  title: string; hits: Hit[]; byId: Map<string, Chunk>; note?: string;
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {note && <p className="text-xs text-amber-700">{note}</p>}
      <ol className="mt-1 space-y-2">
        {hits.map((hit) => {
          const chunk = byId.get(hit.chunk_id)!;
          const page = chunk.regions[0]?.page;
          return (
            <li key={hit.chunk_id} className="text-sm">
              <Link
                className="text-blue-700 hover:underline"
                to={`/paper/${encodeURIComponent(chunk.paper_id)}?chunk=${encodeURIComponent(chunk.id)}`}
              >
                {chunk.paper_id}
              </Link>
              <span className="ml-1 text-xs text-neutral-500">
                {chunk.section ?? "no section"}
                {page ? ` · p${page}` : " · no page geometry"} · {hit.score.toFixed(3)}
              </span>
              <p className="text-neutral-700">{chunk.text.slice(0, 180)}…</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function SearchPanel({ bundle }: { bundle: Bundle }) {
  const [query, setQuery] = useState("");
  const [semantic, setSemantic] = useState<Hit[]>([]);
  const [lexical, setLexical] = useState<Hit[]>([]);
  const [semanticNote, setSemanticNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(bundle.chunks.map((c) => [c.id, c]));

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSemanticNote(null);
    // Lexical first and separately: it is instant, so results are on screen
    // while the 33MB embedding model is still arriving on a first visit.
    setLexical(await search(bundle, query, { mode: "lexical", k: 10 }));
    try {
      setSemantic(await search(bundle, query, { mode: "semantic", k: 10 }));
    } catch (e) {
      setSemantic([]);
      setSemanticNote(
        bundle.semantic.available
          ? `Semantic search failed: ${String(e)}`
          : bundle.semantic.reason === "embed-model-mismatch"
            ? "Semantic search is off: this bundle was built with a different embedding model."
            : "Semantic search is off: this bundle has no vectors.",
      );
    }
    setBusy(false);
  }

  const diff = compareRankings(semantic, lexical);

  return (
    <section className="mt-6">
      <form onSubmit={run} className="flex gap-2">
        <input
          className="flex-1 rounded border px-2 py-1"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the corpus"
          aria-label="Search the corpus"
        />
        <button className="rounded border px-3" disabled={busy}>{busy ? "…" : "Search"}</button>
      </form>

      {(semantic.length > 0 || lexical.length > 0) && (
        <>
          <p className="mt-3 text-xs text-neutral-600">
            {diff.overlap} of 10 results appear in both rankings. The two are never combined into one
            score — read them as two opinions.
          </p>
          <div className="mt-2 grid gap-6 md:grid-cols-2">
            <Results title="Semantic" hits={semantic} byId={byId} note={semanticNote ?? undefined} />
            <Results title="Lexical (BM25)" hits={lexical} byId={byId} />
          </div>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 6: Check it in the browser**

Run: `cd web && npm run dev`
Search for something paraphrased, like `how fast did the bacteria grow`. The first semantic search pauses while the model downloads; lexical results must already be visible. Confirm clicking a result opens that paper at the cited page with a highlight.

- [ ] **Step 7: Commit**

```bash
git add web/src && git commit -m "feat(web): search panel showing semantic and lexical as two rankings"
```

---

### Task 10: The Worker

**Files:**
- Create: `worker/package.json`, `worker/wrangler.toml`, `worker/src/prompt.ts`, `worker/src/caps.ts`, `worker/src/index.ts`
- Test: `worker/src/prompt.test.ts`, `worker/src/caps.test.ts`

**Interfaces:**
- Consumes: `llm-kit` (`compatChat`, `GROQ` from `llm-kit/openai-compat`; `LlmError`, `assertFreeModel` from `llm-kit`). Verified before this plan was written: only `llm-kit/ollama` imports `node:`, so the compat client runs in a Worker; `assertFreeModel("openai/gpt-oss-20b")` passes (it blocks `gpt-4`/`claude`, not `gpt-oss`); a 429 surfaces as `LlmError` with `kind: "rate-limit"` and an empty key as `kind: "no-key"`.
- Note: `AskChunk` is declared in both `worker/src/prompt.ts` and `web/src/ask.ts`. That duplication is deliberate — they are separate packages with no shared module, and a shared one would exist only to hold four fields.
- Produces: `POST /ask` taking `{question, chunks: [{id, paper_id, section, text}]}` and returning `{answer, passages: string[], cited: string[], inTokens, outTokens, ms}`. `passages` is positional — `passages[n-1]` is the chunk the answer labels `[n]` — because `citedChunkIds` de-duplicates into first-seen order and cannot be indexed by label. Task 11's `web/src/ask.ts` is its only client.

- [ ] **Step 1: Set the Worker up**

Run:
```bash
mkdir -p worker/src && cd worker
npm init -y
npm i github:iamsorenl/llm-kit
npm i -D wrangler vitest @cloudflare/workers-types
cd ..
```

Create `worker/wrangler.toml`:

```toml
name = "no-ragrets-ask"
main = "src/index.ts"
compatibility_date = "2026-10-01"

# Rate-limit counters only. No corpus, no question text.
[[kv_namespaces]]
binding = "CAPS"
id = "<fill from: npx wrangler kv namespace create CAPS>"

[vars]
MODEL = "openai/gpt-oss-20b"
ALLOWED_ORIGIN = "https://no-ragrets-research.github.io"
PER_DAY = "15"
PER_VISITOR = "3"
```

`MODEL` must be the id Groq actually serves. Confirm it against the working call in StockPulse rather than trusting this plan — a wrong id returns a 404 that `llm-kit` surfaces as `kind: "api"`.

The key is set once, out of band, and never written to a file in this repo:
```bash
cd worker && npx wrangler secret put GROQ_API_KEY
```

- [ ] **Step 2: Write the failing prompt tests**

Create `worker/src/prompt.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildMessages, citedChunkIds } from "./prompt";

const chunks = [
  { id: "P#1", paper_id: "P", section: "Results", text: "Growth peaked at 30 C." },
  { id: "Q#7", paper_id: "Q", section: "Methods", text: "Cells were grown at 37 C." },
];

describe("buildMessages", () => {
  it("numbers the chunks from 1 and names their paper", () => {
    const messages = buildMessages("What temperature?", chunks);
    const user = messages[messages.length - 1].content;
    expect(user).toContain("[1] P — Results");
    expect(user).toContain("[2] Q — Methods");
    expect(user).toContain("Growth peaked at 30 C.");
    expect(user).toContain("What temperature?");
  });

  it("tells the model to refuse rather than reach", () => {
    const system = buildMessages("q", chunks)[0].content.toLowerCase();
    expect(system).toContain("only");
    expect(system).toContain("does not");
  });
});

describe("citedChunkIds", () => {
  it("maps bracketed numbers back to the ids that were sent", () => {
    expect(citedChunkIds("Growth peaked at 30 C [1], not 37 [2].", chunks))
      .toEqual(["P#1", "Q#7"]);
  });

  it("ignores numbers outside the range and de-duplicates", () => {
    expect(citedChunkIds("see [1] and [1] and [9]", chunks)).toEqual(["P#1"]);
  });

  it("returns nothing when the model cited nothing", () => {
    expect(citedChunkIds("The corpus does not cover this.", chunks)).toEqual([]);
  });
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd worker && npx vitest run`
Expected: FAIL — `Cannot find module './prompt'`.

- [ ] **Step 4: Write `worker/src/prompt.ts`**

```ts
export type AskChunk = { id: string; paper_id: string; section: string | null; text: string };

const SYSTEM = [
  "You answer questions about scientific papers using only the numbered passages provided.",
  "Cite every claim with the bracketed number of the passage it came from, like [2].",
  "If the passages do not contain the answer, say the corpus does not cover it.",
  "Never cite a number that was not provided, and never invent a figure.",
].join(" ");

/** Positional numbering assigned by the sender — the model never names an id,
 *  so a citation cannot point at a chunk that was not sent. */
export function buildMessages(question: string, chunks: AskChunk[]) {
  const passages = chunks
    .map((c, i) => `[${i + 1}] ${c.paper_id} — ${c.section ?? "no section"}\n${c.text}`)
    .join("\n\n");
  return [
    { role: "system", content: SYSTEM },
    { role: "user", content: `Passages:\n\n${passages}\n\nQuestion: ${question}` },
  ];
}

export function citedChunkIds(answer: string, chunks: AskChunk[]): string[] {
  const seen = new Set<string>();
  for (const match of answer.matchAll(/\[(\d+)\]/g)) {
    const index = Number(match[1]) - 1;
    if (index >= 0 && index < chunks.length) seen.add(chunks[index].id);
  }
  return [...seen];
}
```

- [ ] **Step 5: Write the failing cap tests**

Create `worker/src/caps.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { checkAndCount } from "./caps";

function fakeKv() {
  const store = new Map<string, string>();
  return {
    store,
    get: async (key: string) => store.get(key) ?? null,
    put: async (key: string, value: string) => void store.set(key, value),
  };
}

const limits = { perDay: 3, perVisitor: 2 };

describe("checkAndCount", () => {
  it("allows calls under both caps and counts them", async () => {
    const kv = fakeKv();
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits)).toEqual({ allowed: true });
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits)).toEqual({ allowed: true });
  });

  it("stops one visitor at the visitor cap while the day still has room", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits);
    await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits);
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits))
      .toEqual({ allowed: false, reason: "visitor-cap" });
    expect(await checkAndCount(kv, "5.6.7.8", "2026-10-01", limits)).toEqual({ allowed: true });
  });

  it("stops everyone at the daily cap", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "a", "2026-10-01", limits);
    await checkAndCount(kv, "b", "2026-10-01", limits);
    await checkAndCount(kv, "c", "2026-10-01", limits);
    expect(await checkAndCount(kv, "d", "2026-10-01", limits))
      .toEqual({ allowed: false, reason: "day-cap" });
  });

  it("starts fresh on a new day", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "a", "2026-10-01", { perDay: 1, perVisitor: 1 });
    expect(await checkAndCount(kv, "a", "2026-10-02", { perDay: 1, perVisitor: 1 }))
      .toEqual({ allowed: true });
  });
});
```

- [ ] **Step 6: Run to verify they fail**

Run: `cd worker && npx vitest run`
Expected: FAIL — `Cannot find module './caps'`.

- [ ] **Step 7: Write `worker/src/caps.ts`**

```ts
export type KvLike = {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
};
export type Limits = { perDay: number; perVisitor: number };
export type Decision = { allowed: true } | { allowed: false; reason: "day-cap" | "visitor-cap" };

const TWO_DAYS = 60 * 60 * 48;

/** Two counters, both scoped to a UTC day, so nothing needs cleaning up.
 *  Not atomic: two simultaneous requests can both read the same count and the
 *  cap can overshoot by one. That is acceptable for a free-tier courtesy limit
 *  and the upgrade path is a Durable Object, which the free plan does not have. */
export async function checkAndCount(
  kv: KvLike, visitor: string, day: string, limits: Limits,
): Promise<Decision> {
  const dayKey = `day:${day}`;
  const visitorKey = `visitor:${day}:${visitor}`;
  const dayCount = Number((await kv.get(dayKey)) ?? 0);
  const visitorCount = Number((await kv.get(visitorKey)) ?? 0);

  if (dayCount >= limits.perDay) return { allowed: false, reason: "day-cap" };
  if (visitorCount >= limits.perVisitor) return { allowed: false, reason: "visitor-cap" };

  await kv.put(dayKey, String(dayCount + 1), { expirationTtl: TWO_DAYS });
  await kv.put(visitorKey, String(visitorCount + 1), { expirationTtl: TWO_DAYS });
  return { allowed: true };
}
```

- [ ] **Step 8: Run to verify they pass**

Run: `cd worker && npx vitest run`
Expected: all prompt and cap tests pass.

- [ ] **Step 9: Write the handler**

Create `worker/src/index.ts`:

```ts
import { compatChat, GROQ } from "llm-kit/openai-compat";
import { LlmError, assertFreeModel } from "llm-kit";
import { buildMessages, citedChunkIds, type AskChunk } from "./prompt";
import { checkAndCount, type KvLike } from "./caps";

type Env = {
  CAPS: KvLike; GROQ_API_KEY: string; MODEL: string;
  ALLOWED_ORIGIN: string; PER_DAY: string; PER_VISITOR: string;
};

const MAX_CHUNKS = 12;
const MAX_QUESTION = 500;

function json(body: unknown, status: number, origin: string) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": origin,
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "POST, OPTIONS",
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const origin = env.ALLOWED_ORIGIN;
    if (request.method === "OPTIONS") return json({}, 204, origin);
    if (request.method !== "POST") return json({ error: "POST only" }, 405, origin);
    if (new URL(request.url).pathname !== "/ask") return json({ error: "not found" }, 404, origin);

    let body: { question?: string; chunks?: AskChunk[] };
    try {
      body = await request.json();
    } catch {
      return json({ error: "body must be JSON" }, 400, origin);
    }
    const question = (body.question ?? "").trim();
    const chunks = (body.chunks ?? []).slice(0, MAX_CHUNKS);
    if (!question || question.length > MAX_QUESTION) {
      return json({ error: `question must be 1-${MAX_QUESTION} characters` }, 400, origin);
    }
    if (chunks.length === 0) return json({ error: "no passages supplied" }, 400, origin);

    const visitor = request.headers.get("cf-connecting-ip") ?? "unknown";
    const day = new Date().toISOString().slice(0, 10);
    const decision = await checkAndCount(env.CAPS, visitor, day, {
      perDay: Number(env.PER_DAY), perVisitor: Number(env.PER_VISITOR),
    });
    if (!decision.allowed) return json({ error: decision.reason }, 429, origin);

    // Zero cost is a hard constraint, so a paid-looking model id fails here
    // rather than on a bill.
    assertFreeModel(env.MODEL);

    try {
      const reply = await compatChat(buildMessages(question, chunks), {
        baseUrl: GROQ, model: env.MODEL, apiKey: env.GROQ_API_KEY,
        temperature: 0, timeoutMs: 30_000,
      });
      return json({
        answer: reply.content,
        // Positional: passages[n - 1] is the chunk labelled [n] in the answer.
        // `cited` is the subset the model actually referenced, for display only.
        passages: chunks.map((c) => c.id),
        cited: citedChunkIds(reply.content, chunks),
        inTokens: reply.inTokens, outTokens: reply.outTokens, ms: reply.ms,
      }, 200, origin);
    } catch (e) {
      // llm-kit's typed kinds let the UI say which thing broke instead of
      // string-matching an error body.
      const kind = e instanceof LlmError ? e.kind : "unknown";
      const status = kind === "rate-limit" ? 429 : kind === "auth" || kind === "no-key" ? 500 : 502;
      console.log(`ask failed kind=${kind}`);      // counts and kinds only, never the question
      return json({ error: kind }, status, origin);
    }
  },
};
```

- [ ] **Step 10: Deploy it and make one real call**

```bash
cd worker
npx wrangler kv namespace create CAPS     # paste the id into wrangler.toml
npx wrangler secret put GROQ_API_KEY
npx wrangler deploy
curl -s -X POST https://no-ragrets-ask.<your-subdomain>.workers.dev/ask \
  -H 'content-type: application/json' \
  -d '{"question":"At what temperature did growth peak?","chunks":[{"id":"P#1","paper_id":"P","section":"Results","text":"Growth peaked at 30 C."}]}'
```
Expected: a JSON answer citing `[1]`, with `passages: ["P#1"]` and `cited: ["P#1"]`. Then run the same call four times to confirm the fifth returns `{"error":"visitor-cap"}` with status 429.

- [ ] **Step 11: Commit**

```bash
git add worker/ && git commit -m "feat(worker): /ask with llm-kit, positional citations and KV caps"
```

---

### Task 11: The ask box and its degraded states

**Files:**
- Create: `web/src/ask.ts`, `web/src/components/AskBox.tsx`
- Modify: `web/src/components/Reader.tsx` (uncomment the `AskBox` import from Task 8), `web/.env.example`
- Test: `web/src/ask.test.ts`

**Interfaces:**
- Consumes: the Worker's `POST /ask` (Task 10); `search` (Task 7); `Bundle`, `Chunk` (Task 4).
- Produces: `askWorker(question, chunks, opts) -> Promise<AskReply>`; `AskError` with `kind`; `answerSegments(answer, citedIds) -> Segment[]`; `<AskBox bundle scope />` where `scope` is `{kind: "paper", paperId} | {kind: "corpus"}`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/ask.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { askWorker, AskError, answerSegments } from "./ask";

const chunks = [{ id: "P#1", paper_id: "P", section: "Results", text: "Growth peaked at 30 C." }];
const url = "https://worker.example/ask";

describe("askWorker", () => {
  it("returns the answer and citations on success", async () => {
    const fetchImpl = async () =>
      new Response(JSON.stringify({ answer: "30 C [1].", passages: ["P#1"], cited: ["P#1"],
                                    inTokens: 10, outTokens: 4, ms: 500 }), { status: 200 });
    const reply = await askWorker("q", chunks, { url, fetch: fetchImpl });
    expect(reply.answer).toBe("30 C [1].");
    expect(reply.passages).toEqual(["P#1"]);
  });

  it("maps each cap and failure to a distinct kind", async () => {
    const cases: [number, string, string][] = [
      [429, "day-cap", "day-cap"],
      [429, "visitor-cap", "visitor-cap"],
      [429, "rate-limit", "rate-limit"],
      [502, "unreachable", "server"],
      [500, "no-key", "server"],
    ];
    for (const [status, body, kind] of cases) {
      const fetchImpl = async () => new Response(JSON.stringify({ error: body }), { status });
      await expect(askWorker("q", chunks, { url, fetch: fetchImpl }))
        .rejects.toMatchObject({ kind });
    }
  });

  it("reports a network failure as offline rather than a server error", async () => {
    const fetchImpl = async () => { throw new TypeError("Failed to fetch"); };
    await expect(askWorker("q", chunks, { url, fetch: fetchImpl })).rejects.toMatchObject({ kind: "offline" });
  });

  it("refuses to call an unconfigured worker", async () => {
    await expect(askWorker("q", chunks, { url: "", fetch: async () => new Response("{}") }))
      .rejects.toMatchObject({ kind: "not-configured" });
  });
});

describe("answerSegments", () => {
  it("splits an answer into text and citation segments in order, by position", () => {
    // Deliberately cited out of order below: label 2 must still resolve to the
    // SECOND passage sent, not to the second one the model happened to mention.
    expect(answerSegments("Peaked at 30 C [1] not 37 [2].", ["P#1", "Q#7"])).toEqual([
      { kind: "text", text: "Peaked at 30 C " },
      { kind: "citation", label: 1, chunk_id: "P#1" },
      { kind: "text", text: " not 37 " },
      { kind: "citation", label: 2, chunk_id: "Q#7" },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves a citation number with no matching id as plain text", () => {
    expect(answerSegments("see [3]", ["P#1"])).toEqual([
      { kind: "text", text: "see " },
      { kind: "text", text: "[3]" },
    ]);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `Cannot find module './ask'`.

- [ ] **Step 3: Write `web/src/ask.ts`**

```ts
export type AskChunk = { id: string; paper_id: string; section: string | null; text: string };
export type AskReply = {
  answer: string;
  /** Positional: passages[n-1] is the chunk the answer labels [n]. */
  passages: string[];
  /** The subset the model actually referenced. Display only. */
  cited: string[];
  inTokens: number; outTokens: number; ms: number;
};
export type AskErrorKind =
  | "not-configured" | "offline" | "day-cap" | "visitor-cap" | "rate-limit" | "server";

export class AskError extends Error {
  constructor(readonly kind: AskErrorKind, message: string) {
    super(message);
  }
}

export async function askWorker(
  question: string, chunks: AskChunk[],
  { url, fetch: fetchImpl = fetch }: { url: string; fetch?: typeof fetch },
): Promise<AskReply> {
  if (!url) throw new AskError("not-configured", "No ask endpoint is configured.");

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, chunks }),
    });
  } catch (e) {
    // A thrown fetch is the network, not the server: different message for the reader.
    throw new AskError("offline", `Could not reach the answer service: ${String(e)}`);
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    const error = body.error ?? String(response.status);
    const kind: AskErrorKind =
      error === "day-cap" || error === "visitor-cap" || error === "rate-limit" ? error : "server";
    throw new AskError(kind, error);
  }
  return (await response.json()) as AskReply;
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "citation"; label: number; chunk_id: string };

/** Turns `[n]` markers into citation segments, in order.
 *
 * `passages` is positional — the ids in the order they were sent — so label n
 * maps to passages[n-1]. A number with no matching entry stays plain text
 * rather than becoming a link to nothing. */
export function answerSegments(answer: string, passages: string[]): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(/\[(\d+)\]/g)) {
    const at = match.index ?? 0;
    if (at > cursor) segments.push({ kind: "text", text: answer.slice(cursor, at) });
    const label = Number(match[1]);
    const chunk_id = passages[label - 1];
    segments.push(chunk_id ? { kind: "citation", label, chunk_id } : { kind: "text", text: match[0] });
    cursor = at + match[0].length;
  }
  if (cursor < answer.length) segments.push({ kind: "text", text: answer.slice(cursor) });
  return segments;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test`
Expected: all ask tests pass.

- [ ] **Step 5: Write the ask box**

Create `web/src/components/AskBox.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Bundle } from "../bundle";
import { search } from "../retrieval";
import { askWorker, AskError, answerSegments, type AskReply } from "../ask";

const ASK_URL = import.meta.env.VITE_ASK_URL ?? "";
const TOP_K = 8;

export type Scope = { kind: "paper"; paperId: string } | { kind: "corpus" };

export function AskBox({ bundle, scope }: { bundle: Bundle; scope: Scope }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AskReply | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(bundle.chunks.map((c) => [c.id, c]));

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    setReply(null);
    try {
      const mode = bundle.semantic.available ? "semantic" : "lexical";
      const hits = await search(bundle, question, { mode, k: TOP_K * 3 });
      const picked = hits
        .map((h) => byId.get(h.chunk_id)!)
        .filter((c) => scope.kind === "corpus" || c.paper_id === scope.paperId)
        .slice(0, TOP_K);
      if (picked.length === 0) {
        setProblem("Nothing in scope matched that question well enough to ask about.");
      } else {
        setReply(await askWorker(question,
          picked.map(({ id, paper_id, section, text }) => ({ id, paper_id, section, text })),
          { url: ASK_URL }));
      }
    } catch (e) {
      setProblem(
        e instanceof AskError
          ? {
              "not-configured": "Asking is not configured on this deployment. Search still works.",
              offline: "The answer service is unreachable. Search and the papers still work.",
              "day-cap": "The shared daily question limit is used up. Try again tomorrow.",
              "visitor-cap": "You have used your questions for today. Search still works.",
              "rate-limit": "The model is rate-limited right now. Try again in a minute.",
              server: "The answer service failed. Search and the papers still work.",
            }[e.kind]
          : String(e),
      );
    }
    setBusy(false);
  }

  return (
    <section className="mt-4 rounded border p-3">
      <h2 className="text-sm font-semibold">
        Ask {scope.kind === "paper" ? "this paper" : "the corpus"}
      </h2>
      <form onSubmit={ask} className="mt-2 flex gap-2">
        <input
          className="flex-1 rounded border px-2 py-1 text-sm"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What did they measure?"
          aria-label="Ask a question"
        />
        <button className="rounded border px-3 text-sm" disabled={busy || !question.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </form>

      {problem && <p className="mt-2 text-sm text-amber-700">{problem}</p>}

      {reply && (
        <div className="mt-3 text-sm">
          <p className="whitespace-pre-wrap">
            {answerSegments(reply.answer, reply.passages).map((segment, i) =>
              segment.kind === "text" ? (
                <span key={i}>{segment.text}</span>
              ) : (
                <Link
                  key={i}
                  className="mx-0.5 rounded bg-blue-50 px-1 text-blue-700 ring-1 ring-blue-200"
                  to={`/paper/${encodeURIComponent(byId.get(segment.chunk_id)!.paper_id)}?chunk=${encodeURIComponent(segment.chunk_id)}`}
                >
                  [{segment.label}]
                </Link>
              ),
            )}
          </p>
          <p className="mt-2 text-xs text-neutral-500">
            {reply.inTokens} in / {reply.outTokens} out · {reply.ms} ms · answered only from the
            passages cited above
          </p>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 6: Document the one environment variable**

Create `web/.env.example`:

```
# The deployed Worker's /ask endpoint. Unset means asking is disabled and the
# UI says so; search, reading and highlighting do not depend on it.
VITE_ASK_URL=https://no-ragrets-ask.<your-subdomain>.workers.dev/ask
```

Add `AskBox` to `PaperList` as well, with `scope={{ kind: "corpus" }}`, and uncomment the `AskBox` usage in `Reader` from Task 8.

- [ ] **Step 7: Verify both degraded paths by hand**

Run `cd web && npm run dev` with `VITE_ASK_URL` unset: the box must say asking is not configured while search still returns results. Then set it in `web/.env.local`, restart, and ask a real question about a paper. Click a citation chip and confirm it lands on the highlighted region.

- [ ] **Step 8: Commit**

```bash
git add web/src web/.env.example && git commit -m "feat(web): ask box with clickable citations and named degraded states"
```

---

### Task 12: Ship it — bundle release and Pages deploy

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: the bundle from Tasks 1-2, the site from Tasks 4-11.
- Produces: a deployed site. Nothing imports this.

- [ ] **Step 1: Publish the bundle as a Release asset**

```bash
tar -czf /tmp/bundle-no-ragrets-47.tar.gz -C bundles no-ragrets-47
ls -lh /tmp/bundle-no-ragrets-47.tar.gz          # expect roughly 60-70 MB
gh release create bundle-2026-10-01 /tmp/bundle-no-ragrets-47.tar.gz \
  --title "Corpus bundle 2026-10-01" \
  --notes "docling-default export of the 47-paper corpus: manifest, papers, chunks, int8 vectors, PDFs."
```

The PDFs and vectors stay out of git this way, so the repo remains a tool rather than a dataset — the constraint part 1 set — while the deploy still has everything it needs.

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/pages.yml`:

```yaml
name: Deploy reader to Pages

on:
  push:
    branches: [main]
    paths: ["web/**", ".github/workflows/pages.yml"]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "24"

      - name: Fetch the corpus bundle
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          mkdir -p web/public/bundles
          gh release download bundle-2026-10-01 --pattern '*.tar.gz' --dir /tmp
          tar -xzf /tmp/bundle-no-ragrets-47.tar.gz -C web/public/bundles
          test -f web/public/bundles/no-ragrets-47/manifest.json

      - name: Build
        env:
          VITE_ASK_URL: ${{ secrets.VITE_ASK_URL }}
        run: |
          cd web
          npm ci
          npm test
          npm run build

      - uses: actions/upload-pages-artifact@v3
        with:
          path: web/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

Set `VITE_ASK_URL` as a repository secret, and enable Pages with "GitHub Actions" as the source in the repo settings.

`npm test` runs in CI, which means the parity test downloads its model there. If that makes CI slow or flaky, set `SKIP_PARITY=1` for the CI step only — never locally, and note it in the step so the skip is visible.

- [ ] **Step 3: Deploy and check the live site**

Push, watch the workflow, then open `https://no-ragrets-research.github.io/No-RAGrets-v2/` and walk the acceptance list: 47 papers listed, a paper opens and pages, a semantic and a lexical search return separate rankings, a result click lands on a highlighted region, a question returns a cited answer, and a citation chip navigates to the highlight.

- [ ] **Step 4: Update the README**

Add to `README.md` after the Commands section:

```markdown
## The reader

`web/` is a static reader for a bundle built by `python -m lab export`. It lists the corpus, opens
each paper's real PDF, searches the chunks two ways — semantic (bge-small-en-v1.5, vectors built
offline, query embedded in the browser) and lexical (BM25) — and shows every result and every
citation highlighted on the page it came from, using the bbox each chunk already carries.

```
./.venv/bin/python -m lab export docling-default --out bundles/no-ragrets-47
cd web && npm ci && npm run dev
```

The two rankings are never combined into one score. Reading, search and highlighting are entirely
client-side; only answering calls out, to a Cloudflare Worker that holds the model key
(`worker/`, free tier, 15 questions a day and 3 per visitor). With the Worker absent or capped
everything except answering still works, and the UI says which.

The corpus bundle is not in git. It travels as a GitHub Release asset that the Pages workflow
unpacks at build time, so this repo stays a tool rather than a dataset.
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/pages.yml README.md
git commit -m "ci: deploy the reader to Pages with the bundle from a Release asset"
```
