# Ingestion Lab

A benchmark measuring how much of a scientific PDF four extractors recover,
scored entirely without ground-truth labels. This is a tool, not a dataset —
the 47-paper corpus it runs against lives outside this repo and is not
committed here.

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

```
export NORAGRETS_CORPUS=/path/to/papers
```

Use `./.venv/bin/python`, never a bare `python` — the venv pins dependencies
this lab needs, in particular **docling 2.60.0**. Docling 2.123.0 made
threaded docling-parse the default (PR #3764), which drops most of a scanned
PDF's OCR text (open issue #4357) and runs roughly 4x slower on CPU (open
issue #4174). The pin avoids both until upstream resolves them.

## Commands

```
./.venv/bin/python -m lab manifest build       # hash + describe every PDF in the corpus
./.venv/bin/python -m lab run <runner>         # run one runner over the corpus
./.venv/bin/python -m lab compare              # aggregate all runners into results/REPORT.md
./.venv/bin/python -m lab import-baseline DIR  # import existing DoclingDocument JSON as a baseline
```

`run` caches per-paper results and skips work already done; `--force` ignores
the cache, `--limit N` runs only the first N papers.

## Docs

- Spec: `docs/superpowers/specs/2026-09-28-ingestion-lab-design.md`
- Plan: `docs/superpowers/plans/2026-09-28-ingestion-lab.md`
