# Part 2a — Reader and Q&A over one corpus bundle

Date: 2026-10-01
Status: approved design, not yet implemented
Repo: No-RAGrets-Research/No-RAGrets-v2

## Purpose

A static site that reads the 47-paper corpus, searches it semantically, answers questions about it,
and shows every answer's source highlighted on the actual PDF page it came from.

This is part 2a of the No RAGrets v2 rebuild. Part 1 (the ingestion lab) is merged. Part 2 split in
two during design: **2a is this document** — the reader over one corpus bundle. **2b** is bring-your-own
corpus: a corpus switcher, saved corpora, and in-browser ingestion. 2b is deliberately not designed
here, and the one thing 2a owes it is a bundle format loaded by id, with nothing about "the 47 papers"
baked into the app.

## What the lab already settled

From `docs/decisions/2026-09-30-ui-hosting.md` and `results/REPORT.md`, measured not assumed:

- **Ingestion is `docling-default`, run offline.** A bare `DocumentConverter()`. Tuning lost
  (-4.43% characters, 43 of 47 papers worse), so there is no tuned variant to prefer.
- **Browser-side pdf.js is not the ingestion path.** 0 tables across 47 papers, 88.9% of substantial
  paragraphs spanning the column gutter against docling's 26.3%, and 0 characters returned silently
  on the one scanned paper. pdf.js appears in 2b only, for ad-hoc uploads, with those limits stated
  in the UI.
- **Provenance geometry already exists and is clean.** Every one of the 15,367 docling blocks carries
  a bbox, and all 2,800 chunks resolve to blocks that all have one. `lab/runners.py:300` normalizes to
  `[x0, top, x1, bottom]` in top-down PDF points, flipping docling's bottom-left origin once, and
  returns null honestly when a page height is missing.
- Scale: 2,800 chunks, median 1,024 chars, 2.18M chars of text; 47 PDFs totalling 68MB, largest 5.2MB.
  Both inside GitHub Pages' limits.

v1's UI is not the starting point. Its provenance worked through a server API that resolved a relation
to a location, and without it the client fell back to three tiers of fuzzy text search, a substring
"approximate match" that highlighted any block merely mentioning a search term, a filename regex that
guessed PDF paths, and two copies of the bottom-left coordinate flip that disagreed with each other.
None of that is needed when a chunk carries its own rectangles. `DoclingRenderer` (555 lines) and
`AnnotatedView` (837 lines) are not ported. The ideas in `PDFViewer` and `BoundingBoxOverlay` (265
lines together) are rewritten against the clean bbox contract.

## Constraints

- **Zero cost.** Free hosting, free-tier model, no service that can bill. One Cloudflare Worker on the
  free tier is the only server-side component, and it exists solely to hold the model key.
- **Search, reading and provenance work with the Worker absent.** Only answering needs it.
- **No composite scores.** Semantic and lexical rankings are shown separately, never blended into one
  number. Same rule the lab enforced, and here it is what makes the embeddings' value visible.
- The corpus ships publicly, including the PDFs. Soren confirmed on 2026-09-28 that these papers are
  not copyright-encumbered; the earlier "not redistributable" framing was wrong and is superseded.

## Scope

In: bundle format, `lab export`, the static reader, semantic + lexical search, highlight-on-PDF
provenance, and question answering over retrieved chunks via one Worker.

Out: the corpus switcher and saved corpora (2b), in-browser ingestion (2b), multi-turn conversation
(Part 3), relation extraction and the graph view (Part 4 and beyond), figure extraction, a mobile
reflow reading mode, and any docling-to-HTML reconstruction view.

## Architecture

```
lab export  ──▶  bundles/<corpus-id>/   ──▶  static site (GitHub Pages)
 (offline)        manifest.json               paper list, reader, search
                  papers.json                 retrieval runs in the browser
                  chunks.json                        │
                  vectors.bin                        │ POST /ask  (top-k chunk texts)
                  pdfs/*.pdf                         ▼
                                              Worker (holds the model key)
                                                     │
                                                     ▼  Groq gpt-oss-20b
```

### The bundle

```
bundles/no-ragrets-47/
  manifest.json     {corpus_id, name, built_at, source_runner, runner_version,
                     embed_model, dim, counts:{papers,chunks},
                     files:{papers.json|chunks.json|vectors.bin: sha256}}
                    (the PDFs are hashed per paper in papers.json instead)
  papers.json       [{paper_id, filename, pages, sha256}]
  chunks.json       [{id, paper_id, section, text, chars, regions}]
  vectors.bin       int8 matrix, row-major, counts.chunks x dim, plus one float32 scale per row
  pdfs/<filename>   the PDFs named in papers.json
```

`regions` is the design's load-bearing decision:

```
regions: [{page: 4, rects: [[x0, top, x1, bottom], ...]}, ...]
```

Export resolves `chunk.block_ids` against `blocks[]` once, at build time, and writes the resulting
geometry into the chunk. `block_ids` are positional indices into that paper's `blocks[]`, which is why
the resolution has to happen where both lists are in hand. Rects are grouped by page because a chunk can cross a page break inside a
section. The browser therefore never resolves a block reference, never loads `blocks[]`, and cannot
drift out of sync with it — which is the class of bug v1's provenance lived in.

`embed_model` is enforced at load: the web app holds the model id it will load as a constant, and if it
does not match the manifest's, semantic search is disabled with that reason shown. A mismatch produces cosine scores across
two different vector spaces, which look plausible and are meaningless — the same shape of failure as
v1's unreproducible headline, so it gets a guard rather than a comment.

Text is served uncompressed; the Pages CDN gzips it in transit, which is cheaper than a decompression
path in JS.

### `lab export`

```
python -m lab export docling-default --out bundles/no-ragrets-47 [--no-embed]
```

Reads `results/<runner>.jsonl` and `corpus.manifest.json`. Copies each paper's PDF from
`$NORAGRETS_CORPUS`. Embeds chunk text with `fastembed` using **bge-small-en-v1.5** — the same weights
transformers.js loads in the browser, which is what keeps one vector space. One new offline dependency
(ONNX runtime, no torch); nothing is added to the hosted site's runtime.

Quantization is per-row symmetric max-abs to int8. Export reports the mean cosine error between int8
and float32 vectors over a sample, and top-10 overlap on a few fixed queries, so the compression's
cost is measured rather than asserted.

`--no-embed` rewrites the text side and leaves `vectors.bin` untouched, so fixing a chunking or
geometry bug does not re-pay the embedding cost.

### The site

Vite + React + Tailwind, new in this repo under `web/`. Deployed to GitHub Pages by a workflow that
downloads the bundle tarball from a GitHub Release and unpacks it into the build. The PDFs and
vectors stay out of git: the lab repo remains a tool, not a dataset, which was a stated constraint of
part 1 and survives intact.

Routes:

- `/` — the 47 papers: `paper_id` as the display name (it is the paper's filename stem, e.g.
  `A. Priyadarsini et al. 2023`), pages, chunk count, and a corpus-wide search box.
- `/paper/:paper_id` — the reader. Real PDF pages via `react-pdf`, an outline built from the chunks'
  `section` values, and an "ask about this paper" box.

Search results are a panel over either route, not a page of their own: ranked chunks showing paper,
section and score. Clicking one navigates to the paper, scrolls to the first region's page, and flashes
its rects. Ask has a scope toggle — this paper, or the whole corpus.

### Retrieval

One module of pure functions, no React, tested in Node:

```
search(query, {mode: "semantic" | "lexical", k}) -> [{chunk_id, score}]
```

Semantic dequantizes `vectors.bin` into a `Float32Array` once at load — 4.3MB of memory against a
1.1MB download — and does float cosine. This avoids int8 dot-product subtleties for memory nobody is
short of. The query embedder lazy-loads on the first semantic search, about 33MB cached after once, so
the app is usable before it arrives and lexical search covers the gap.

Lexical is BM25 built in memory from chunk text at load. On 2.2MB it is instant, and it is the baseline
semantic search has to visibly beat.

### Highlighting

The IR is already top-down PDF points, so the entire transform is one function:

```
left: x0 * scale, top: top * scale, width: (x1 - x0) * scale, height: (bottom - top) * scale
```

Absolutely-positioned divs over the rendered page, not a canvas. No origin flip anywhere in the
frontend — the flip happens once, offline, in `lab/runners.py`.

### The Worker

`POST /ask` takes the question plus the top-k chunks the browser already retrieved (id, paper_id,
section, text) and returns an answer plus citation indices into that list. The Worker does not search,
does not hold the corpus, and holds the model key as a Worker secret.

Citation indices are positional and assigned by the sender; the frontend maps `[n]` back to chunk ids
to turn a citation into a click that lands on a highlighted rectangle. Indices are never parsed out of
model prose.

The prompt's instruction set is narrow: answer only from the supplied chunks, cite with `[n]`, and say
the corpus does not cover it rather than reaching.

Caps use Workers KV — a daily counter and a per-visitor counter keyed on `cf-connecting-ip` — at 15/day
and 3/visitor to start, the pattern already running on the SLAC demo. At that cap the counting costs
about 30 KV writes a day against a 1,000/day free allowance. CORS allows the Pages origin only. Logs
record counts, not question text.

## Degraded states

Each is shown with its reason. None guesses, because guessing is what made v1's provenance
untrustworthy.

| Condition | Behaviour |
|---|---|
| PDF missing from the bundle | Reader shows the chunk text panel with "PDF not in this bundle". Citations still resolve to text — the panel is what the model saw. |
| `embed_model` mismatch | Semantic search disabled, reason shown. Lexical still works. |
| `vectors.bin` absent, or the embedder fails to load | Lexical only, stated in the UI. |
| Worker down, or cap reached | The UI says which. Search and reading unaffected. No cached or best-guess answer. |

## Testing

- **Python**, plain asserts in `lab/test_lab.py`'s existing style, over a two-paper fixture: regions
  resolve to the right page and rects; manifest hashes match the files on disk; `--no-embed` leaves
  `vectors.bin` byte-identical; quantization error is reported.
- **Frontend**, vitest on the pure parts: the rect transform against a known geometry; BM25 ranking on
  a tiny fixture; cosine top-k over hand-made vectors; and the `embed_model` guard actually refusing
  rather than warning.
- **Worker**: cap logic and prompt assembly are pure functions tested in Node. The fetch handler stays
  thin enough to read.
- **One throwaway verification script**, labelled as such and not committed as a test: render a page
  from three papers at a fixed scale with their rects drawn, for a human to eyeball once. A green rect
  transform test does not prove docling's bboxes land on the rendered page — a rotation, a cropbox
  offset, or a page-size mismatch misplaces every highlight while every unit test passes. This is the
  risk the automated tests cannot reach, and it gets checked before the viewer is built on top of it.

## Acceptance

1. `python -m lab export docling-default` produces a bundle whose manifest hashes match its files, and
   whose chunk count matches `results/docling-default.jsonl`.
2. Every chunk in the bundle carries at least one region, and every region's page exists in that
   paper's page count.
3. The site loads the bundle, lists 47 papers, and opens any paper's real PDF.
4. A semantic search and a lexical search both return ranked chunks, shown as separate rankings with no
   blended score anywhere.
5. Clicking a result lands on the right page with rects drawn over the text that result quoted —
   verified by eye on three papers, including one two-column layout.
6. Asking a question returns an answer whose citations click through to highlighted regions, and a
   question the corpus does not cover returns a refusal rather than an invention.
7. With the Worker unreachable, search, reading and highlighting still work, and the UI says why asking
   does not.
8. Frontend and Python test suites pass.

## Explicitly not building

- **A vector database.** 2,800 chunks is a 1.1MB file and a loop. A vector DB here would be a
  dependency bought with nothing. Reconsider when a corpus makes client-side cosine measurably slow.
- **Blended ranking.** Semantic and lexical stay separate for the same reason the lab refused a
  composite score.
- **A docling-to-HTML reading view.** It existed in v1 because the PDF could not be trusted to carry
  the provenance; now it can.
- **In-browser ingestion.** 2b, and the lab measured why it is the weaker path.
- **An MCP server.** The bundle is a static file read by one web app. Reconsider if a corpus and its
  results ever need querying interactively from other projects.
- **Answer caching or an answer history.** Part 3's conversation layer is where state belongs.
