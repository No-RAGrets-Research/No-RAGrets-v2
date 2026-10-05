# Ingestion Lab

A benchmark measuring how much of a scientific PDF four extractors recover,
scored entirely without ground-truth labels. This is a tool, not a dataset —
the 47-paper corpus it runs against lives outside this repo and is not
committed here.

## Where the corpus comes from

The 47 PDFs this lab runs against are not in this repo and are not
redistributable — they are scientific papers with their own copyright, not
this project's to publish. `corpus.manifest.json` records each paper's
filename and sha256, so a run can be verified against a specific corpus
snapshot without ever shipping the PDFs themselves. `$NORAGRETS_CORPUS` must
point at a local directory of PDFs matching that manifest (see `python -m lab
manifest verify`); for this project's own runs, that directory is
`No-RAGrets-Master/data/papers`. A fresh clone of this repo has code, the
manifest, and `results/REPORT.md`, but no way to reproduce a run without
separately obtaining a corpus that matches the manifest.

## Why no labels

No-RAGrets v1 had no way to tell whether an extractor was dropping content
short of manually re-reading every PDF. This lab does not solve that; it
substitutes measurements that need no ground truth — coverage against a floor
runner, cross-runner agreement, dropped pages, table structure, chunk health,
reading order, and cost — and states plainly where each one is silent. See
`results/REPORT.md` for what the numbers do and do not show.

## The four runners

- `pdfplumber` — the floor. MIT-licensed, no OCR, reads the embedded text
  layer directly.
- `docling-default` — a bare `DocumentConverter()`, reproducing what v1 ran.
- `docling-tuned` — adds `force_full_page_ocr=True` with an explicitly pinned
  V4 backend. On docling 2.60.0 every other pipeline option this runner might
  have tuned is already the default.
- `pdfjs-node` — the extractor the shipped browser-side product would
  actually use.

## Setup

Built and run on Python 3.12.8 and Node 24. Every command below runs from the
repo root.

```
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
npm ci
export NORAGRETS_CORPUS=/path/to/papers
```

Use `./.venv/bin/python`, never a bare `python` — the venv pins dependencies
this lab needs, in particular **docling 2.60.0**. Docling 2.123.0 made
threaded docling-parse the default (PR #3764), which drops most of a scanned
PDF's OCR text (open issue #4357) and runs roughly 4x slower on CPU (open
issue #4174). The pin avoids both until upstream resolves them.

`import-baseline` additionally needs a directory of pre-converted
DoclingDocument JSON — in this project, `No-RAGrets-Master/data/docling_json`
— since importing an existing baseline is how `docling-default` avoids
re-paying its own compute cost.

Determinism is not a report column. It is verified separately by re-running a
runner and comparing `ir.content_hash()` across the two results — an equal
hash means byte-for-byte identical output apart from timing.

## Commands

```
./.venv/bin/python -m lab manifest build       # hash + describe every PDF in the corpus
./.venv/bin/python -m lab run <runner>         # run one runner over the corpus
./.venv/bin/python -m lab compare              # aggregate all runners into results/REPORT.md
./.venv/bin/python -m lab import-baseline DIR  # import existing DoclingDocument JSON as a baseline
```

`run` caches per-paper results and skips work already done; `--force` ignores
the cache, `--limit N` runs only the first N papers. The cache key is the
paper's sha256 plus the runner's version string, so a library upgrade
re-converts instead of replaying stale output. One consequence: an imported
baseline is stamped `docling==2.60.0 (imported)`, which no live run can match,
so `run docling-default` after `import-baseline` always re-converts. That is
not the documented workflow — the baseline is meant to stay imported.

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

## Docs

- Spec: `docs/superpowers/specs/2026-09-28-ingestion-lab-design.md`
- Plan: `docs/superpowers/plans/2026-09-28-ingestion-lab.md`
