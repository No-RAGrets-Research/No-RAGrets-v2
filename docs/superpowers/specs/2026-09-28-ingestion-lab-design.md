# Ingestion Lab — Design

Date: 2026-09-28
Status: approved design, not yet implemented
Repo: No-RAGrets-Research/No-RAGrets-v2

## Purpose

Measure PDF ingestion quality before changing it, so that any later improvement is attributable.

This is part 1 of 4 in the No RAGrets v2 rebuild (ingestion lab, then UI, then RAG conversation,
then anomaly detection). The lab exists first because v1 shipped numbers nobody can reproduce:
its headline "96.45%" never recorded how per-triple judge scores aggregate, so it cannot be used
as a baseline for anything.

The lab answers two questions:

1. Does a tuned Docling configuration extract measurably more of a paper than v1's default one?
2. Is browser-side extraction (`pdfExtractor.ts`, the path the shipped app would use) good enough
   to keep the zero-server hosting design?

## Constraints

- **Zero cost.** No model calls in the harness, no paid services, no hosting. A free tier that can
  bill is disqualified. Every metric is mechanical and runs locally.
- **No ground truth exists.** A repo-wide search of No-RAGrets-Master found no human-labeled
  reference text, tables, or relations for any paper in `data/papers/`. The only trace is a printed
  TODO at `archive/relation_llm_judgement/scripts/run_pilot.py:163` — v1 flagged annotation and
  never did it. Every metric here is therefore label-free by necessity, not preference.
- **No LLM judge.** v1's own data shows six judges scoring the same 94 relations between 66% and
  100% (`archive/relation_llm_judgement/results/phase2_multipaper_20251120_122619/statistics.json`).
  That spread is wider than any effect this lab is trying to detect.
- **v2 is a tool, not a dataset.** The paper corpus stays out of the repo so v2 remains a clean
  ingestion tool that anyone can point at their own papers.

## Scope

In: PDF → blocks → tables → chunks.

Out: relation extraction, the Mistral-7B text extractor, the VLM visual extractor, Dgraph, and
anything requiring a GPU. Including them would mix model nondeterminism into the extraction signal
the lab is built to isolate.

Also out: the A→B vs B→A self-consistency check (v1 agreed with itself on 16/93 High pairs). That
metric belongs to the similarity layer, downstream of this lab. It is the number this lab makes
attributable later — it is not a metric of this lab.

## Layout

```
lab/
  runners.py    four extractors -> one common IR
  metrics.py    label-free scoring over the IR
  cli.py        manifest | run | compare
  __main__.py   one line, so `python -m lab` works
  pdfjs_runner.mjs  Node side of the pdfjs runner
  test_lab.py   asserts over hand-written IR; one pdfplumber smoke test
corpus/                 gitignored, located by $NORAGRETS_CORPUS
corpus.manifest.json    committed
results/*.jsonl         gitignored (bulky derived text)
results/REPORT.md       committed (aggregate numbers only)
fixtures/tiny.pdf       committed, a few hundred bytes
```

## Intermediate representation

Every runner emits the same JSON per paper. This IR is the interface the UI, RAG, and anomaly parts
consume later, so it is the one thing in the lab worth designing carefully.

```json
{
  "paper_id": "Burrows et al 1984",
  "runner": "docling-default",
  "runner_version": "docling==2.60.0",
  "pdf_sha256": "…",
  "pages": 14,
  "wall_seconds": 12.3,
  "blocks": [{"page": 3, "kind": "paragraph", "text": "…", "bbox": [0,0,0,0], "order": 17}],
  "tables": [{"page": 5, "rows": 4, "cols": 6, "cells": [["…"]], "caption": "…"}],
  "chunks": [{"id": 0, "text": "…", "block_ids": [3,4,5], "section": "Methods", "chars": 812}]
}
```

`block.kind` is one of `paragraph`, `section_header`, `table`, `caption`, `other`.

`bbox` is nullable. Docling gives provenance; pdf.js and pdfplumber give spans. Normalizing that
away would hide a real capability difference between runners, so runners that have no bbox write
`null` and the reading-order metric skips them rather than guessing.

## Runners

| Name | What it is | Why it is here |
|---|---|---|
| `docling-default` | bare `DocumentConverter()` | exactly what v1 ran. This is the baseline. |
| `docling-tuned` | `do_ocr=True`, TableFormer ACCURATE, explicit `DoclingParseDocumentBackend` | the improvement candidate |
| `pdfjs-node` | `pdfExtractor.ts` logic run headless under Node via `pdfjs_runner.mjs` | the path the shipped product actually hits |
| `pdfplumber` | MIT, pdfminer.six-based | the floor, and the reference for the coverage metric |

`docling-default` costs zero compute on first run: the 47 files in
`No-RAGrets-Master/data/docling_json/` were produced by a bare `DocumentConverter()` at docling
2.60.0 (`pipeline/kg_gen_pipeline/core/pdf_converter.py:44`), so they are imported as the baseline.
Re-running it from PDFs must stay possible and must reproduce them.

`pdfjs-node` is a port, not an import: `ui/no-ragrets-ui/src/utils/pdfExtractor.ts` lives in
No-RAGrets-Master and pulls in that app's build. `pdfjs_runner.mjs` reimplements its extraction call
against `pdfjs-dist` and emits the IR as JSON on stdout, which `runners.py` shells out to. If the two
ever diverge the lab is measuring the wrong thing, so the port keeps a comment naming its source file.

The floor is pdfplumber, not PyMuPDF. PyMuPDF is AGPL and this repo is public — the same licensing
trap already identified in dots.ocr.

### Docling version

Pin `docling==2.60.0`, and pass `backend=DoclingParseDocumentBackend` explicitly regardless of
version. Verified 2026-09-28:

- 2.123.0 made threaded docling-parse the default (PR #3764) and introduced two regressions that
  are still open: [#4174](https://github.com/docling-project/docling/issues/4174) (~4x slower CPU
  conversion) and [#4357](https://github.com/docling-project/docling/issues/4357) (drops most of a
  scanned PDF's embedded OCR text layer, confirmed present at 2.126.0).
- 2.60.0 predates both. Latest is 2.130.0 and is affected. 2.122.0 is merely the last release before
  the break and is not a target.

Two metrics below exist specifically to catch these classes of failure if the pin ever moves.

### Chunker

One chunker, applied to every runner's block stream: split on `section_header`, then pack blocks to
a character budget on sentence boundaries. Held constant in run 1 so that extraction is the only
variable. Chunker variants become axis two once extraction is settled.

Sentence splitting is regex-based, not spaCy. **Known ceiling:** it will mis-split on abbreviations
and inline citations like "et al. 1984". Upgrade path is swapping the one `split_sentences()`
function for spaCy if chunk-health numbers turn out to be dominated by split noise rather than
extraction quality.

## Metrics

All mechanical. All computed from the IR, so they are runner-agnostic and testable without a PDF.

1. **Coverage** — characters per page as a ratio of the pdfplumber floor. Pages under 10% of floor
   are counted as dropped. This is the #4357-class detector.
2. **Table arithmetic** — for tables containing a row or column labeled total/sum, does it reconcile
   within tolerance. This is the only metric here that can be flatly right or wrong without labels,
   so it carries the most weight in the report.
3. **Table structure** — rectangularity (every row has the same column count) and non-empty cell
   ratio.
4. **Cross-runner agreement** — per-page character 3-gram similarity between each runner pair.
   Disagreement localizes a conflict; coverage then says which runner lost it.
5. **Reading order** — fraction of adjacent blocks monotonic in (page, y, x), plus a count of blocks
   ending mid-word. Skipped for runners with null bbox.
6. **Structure proxy** — whether abstract, introduction, methods, results, discussion, and
   references are each detected exactly once. Papers essentially always have them; a miss is
   structure loss.
7. **Chunk health** — size distribution, orphan chunks under 100 characters, chunks starting
   mid-sentence, chunks straddling a section boundary.
8. **Determinism and cost** — the same PDF run twice must produce an identical IR hash; wall seconds
   per page is recorded. The timing figure is the #4174-class detector.

No metric is aggregated into a single score. v1's unreproducible "96.45%" came from exactly that
move, and the aggregation formula was never written down.

## Environment

Python 3.11 (Master's `pipeline/setup.py:7` says >=3.11 while its README says 3.8+; 3.11 is the one
that actually ran). Dependencies: `docling==2.60.0`, `docling-core`, `pdfplumber`, and Node with
`pdfjs-dist` for the one `.mjs` runner. Nothing else — the harness makes no model calls.

## Corpus handling

`corpus.manifest.json` is committed and holds, per paper: filename, sha256, DOI where known, page
count, and a scanned-vs-digital flag. A run verifies every PDF against the manifest and fails loudly
on a mismatch or an extra file.

This catches silent drift, including the case already present in Master: `data/docling_json/` holds
49 JSON files for 47 PDFs, because the cache is a filename-stem existence check
(`pdf_converter.py:62-64`) that is neither content-hash nor Docling-version aware. Two entries
(`Nguyen et al. 2021`, `Vercherskaya et al. 2001`) have no source PDF at all.

The lab's own cache keys on `pdf_sha256` plus `runner_version`, so changing either invalidates it.

## Output

`python -m lab compare` reads `results/*.jsonl` and writes `results/REPORT.md`: one row per runner,
one column per metric, plus a per-paper outlier list naming the worst five papers per metric.

`results/*.jsonl` stays gitignored — it holds the full extracted text of every paper, which makes
v2 a dataset again. Only the aggregate report is committed.

## Testing

One file, `test_lab.py`, asserts and a `__main__`. No pytest, no fixtures.

- Metrics are fed hand-written IR dicts with known answers.
- The table-arithmetic check is tested both ways: a table whose sums reconcile must pass, and a copy
  with one corrupted cell must fail. A metric that cannot fail is not a metric.
- One smoke test runs the pdfplumber runner against `fixtures/tiny.pdf` and asserts the IR
  validates.

## Acceptance

The lab is done when:

1. All four runners produce validating IR for all 47 papers.
2. `results/REPORT.md` shows all eight metric families for all four runners.
3. `docling-default` re-run from PDFs reproduces the imported baseline JSON.
4. `test_lab.py` passes, including the corrupted-table case.
5. The report states plainly whether `pdfjs-node` is within tolerance of `docling-tuned` on coverage
   and table structure — because that answer decides whether the zero-server hosting design holds.

## Explicitly not building

- An MCP server wrapper. This is a local batch harness with nothing live to read or write across
  sessions; an MCP server here would be a tool looking for a job. Reconsider if the corpus and
  results ever need to be queried interactively from other projects.
- Parallel execution. 47 papers run overnight. Add it when a run outlasts your patience.
- A config file. `$NORAGRETS_CORPUS` plus CLI flags cover every knob the lab has.
- A single composite quality score. See the note under Metrics.
- Any re-run of the Dgraph layer, any swap of the Mistral-7B extractor.
