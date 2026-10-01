# Decision — UI and hosting for Part 2

Date: 2026-09-30. Settled from the ingestion lab's measured results (`results/REPORT.md`),
which existed to answer exactly this. Supersedes the spec's open question 2.

## The question the lab was built to answer

> Is browser-side extraction (`pdfExtractor.ts`) good enough to keep the zero-server hosting design?

## Answer: no as an ingestion path, yes as a hosting design

Those are two questions the spec ran together. Split, both have clear answers.

**Browser-side extraction is not good enough to be the product's ingestion path.** Verified from
`results/*.jsonl`, not quoted from the report:

| | `pdfjs-node` | `docling-default` |
|---|---|---|
| chars, table cells included | 2,265,452 | **2,321,204** |
| tables, 47 papers | **0** | 129 |
| substantial paragraphs spanning the column gutter | **88.9%** (1461/1643) | 26.3% (985/3752) |
| the one scanned paper (`Xin et al. 2004`) | **0 chars, silently** | 18,471 chars |

Coverage is the only axis where pdf.js is competitive, and it still loses. Tables are absent by
construction, which for scientific papers removes most of the numbers worth retrieving. Column
merging is the quiet one: pdf.js recovers the characters but delivers 89% of its substantial
paragraphs in an order a RAG chunk cannot use. (Known ceiling of that metric: a genuinely
full-width paragraph counts as spanning, so 88.9% is an upper bound — but docling on the same
metric reads 26.3%, so the gap is real.)

**The zero-server hosting design survives anyway**, because nothing forces extraction to happen at
serve time. Ingestion is a batch step run locally with docling — which is what the lab already
does — and the app ships a prebuilt index. No server, no bill, and the runner that wins gets used.

Also settled by the same evidence: use `docling-default`, a bare `DocumentConverter()`. Tuning was
measured and lost (-4.43% characters, 43 of 47 papers worse). Do not re-run that experiment.

## What Part 2 builds

Static site, two modes, one deploy target (GitHub Pages — free, no billing possible):

1. **Corpus mode** — reads a prebuilt index generated offline by the lab's docling path. This is
   the real research tool. Private deploy or local, because the 47 papers are not redistributable
   and a public site serving their chunk text would be republishing copyrighted text.
2. **Demo mode** — public, user drops their own PDF, extraction via pdf.js in the browser. Ships
   with the measured limits stated in the UI, not buried: no tables, column merging on two-column
   layouts, and a hard guard on the scanned case (near-zero chars per page must say "this PDF has
   no text layer" rather than return an empty result).

Retrieval starts lexical, client-side, over the prebuilt chunks — 2,800 chunks and ~2.3M characters
is small enough that a vector DB would be a dependency bought with nothing. Add embeddings when
lexical measurably falls short.

Open, not decided here: Part 3's conversation layer needs an LLM call, and a browser-only app has
nowhere safe to keep a key. Either a free-tier proxy (Cloudflare Worker) or the user supplies their
own key. That is Part 3's problem, and it does not change anything above.

## Amended 2026-10-01, during Part 2a design

Two things above are now wrong, both my errors, corrected by Soren:

1. **"Private, because the 47 papers aren't redistributable" is withdrawn.** Soren's correction of
   2026-09-28 stands: these papers are not copyright-encumbered. The corpus — chunk text and the PDFs
   — ships publicly, and corpus mode needs no private deploy. The PDFs still stay out of git (they
   travel as a GitHub Release asset the Pages build unpacks), so the repo remains a tool rather than a
   dataset, but that is a repo-hygiene choice now, not a rights one.
2. **"Zero-server" is now "zero-server for search and provenance".** Q&A is in scope for Part 2, and
   Soren chose a free Cloudflare Worker holding the model key over asking each visitor for their own.
   So there is exactly one server-side component, it holds no corpus and no state beyond rate-limit
   counters, and search, reading and highlighting all keep working when it is down.

Part 2 also split in two during design. 2a is the reader over one corpus bundle
(`docs/superpowers/specs/2026-10-01-part2a-reader-design.md`); 2b is bring-your-own corpus — the
switcher, saved corpora, and in-browser pdf.js ingestion — which is where the measured pdf.js limits
above actually land.
