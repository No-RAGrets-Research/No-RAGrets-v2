# Ingestion Lab Report

Floor runner: `pdfplumber`. Coverage is measured against it, so its own coverage row is 1.0 by definition.

No column is a quality score and no column should be averaged with another. When `arith checked` is nonzero, read `arith pass` first — it is the only column that can be flatly wrong.

Caveat: on this corpus, `arith checked` reads 0 across all runners because these papers contain literature-comparison tables with quantity names like `Total biomass (g/L)` rather than aggregate-total rows or columns. This is not a failure of any runner; it is the honest outcome of a label-free metric on a corpus without checkable totals. The measurement weight falls to coverage, dropped pages, and cross-runner agreement.

Caveat: `order monotonic` is not evidence of correct reading order. It reads 1.000 for every runner because each runner already emits blocks in sorted order (the docling path sorts by page, top, left; the line-based runners bucket lines by rounded top), so asking whether sorted output is sorted always answers yes. `midword` is the weaker signal that actually varies.

Caveat: `sections/6` and the chunk columns compare within a runner family, not across. The docling runners supply their own `section_header` labels, while `pdfplumber` and `pdfjs-node` route all text through a font-blind classifier. Measured on one paper: docling found 5 of 6 canonical sections, pdfplumber 3, pdfjs 2 — reading that as "docling detects structure better" would be an artifact of the classifier, not a measurement.

Caveat: read `dropped pages` alongside `cov. mean-of-medians`, never that figure alone. Measured: `docling-default` had a median page ratio of 1.002 while its total characters were 0.909x the floor, because it lost one whole page rather than degrading uniformly. The mean-of-medians alone hides that entirely.

| runner | papers | cov. papers | cov. mean-of-medians | dropped pages | chars | order monotonic | midword | sections/6 | tables | empty cells | arith checked | arith pass | chunks | orphans | s/page |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `docling-default` | 47 | 3 | 1.021 | 5 | 222219 | 1.000 | 2477 | 3.83 | 129 | 0.078 | 0 | — | 2763 | 336 | — |
| `pdfjs-node` | 3 | 3 | 1.002 | 0 | 242260 | 1.000 | 123 | 2.33 | 0 | — | 0 | — | 277 | 15 | 0.03 |
| `pdfplumber` | 3 | 3 | 1.000 | 0 | 241520 | 1.000 | 133 | 2.33 | 1 | 1.000 | 0 | — | 301 | 22 | 0.08 |

## Cross-runner agreement

| pair | papers | mean of per-paper medians |
|---|---|---|
| docling-default vs pdfjs-node | 3 | 0.948 |
| docling-default vs pdfplumber | 3 | 0.933 |
| pdfjs-node vs pdfplumber | 3 | 0.976 |

## Worst five papers per runner, by coverage

- `docling-default`: A. Priyadarsini et al. 2023 (1.002), Ahmadi & Lackner 2024 (1.008), Adegbola thesis High Density Cultures (1.053)
- `pdfjs-node`: Ahmadi & Lackner 2024 (1.001), Adegbola thesis High Density Cultures (1.001), A. Priyadarsini et al. 2023 (1.002)
- `pdfplumber`: A. Priyadarsini et al. 2023 (1.0), Adegbola thesis High Density Cultures (1.0), Ahmadi & Lackner 2024 (1.0)

## Chunk straddling

- `docling-default`: 0 chunks cross a section header; median chunk 958 chars
- `pdfjs-node`: 0 chunks cross a section header; median chunk 989 chars
- `pdfplumber`: 0 chunks cross a section header; median chunk 908 chars
