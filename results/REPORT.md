# Ingestion Lab Report

Floor runner: `pdfplumber`. Coverage is measured against it, so its own coverage row is 1.0 by definition.

No column is a quality score and no column should be averaged with another. When `arith checked` is nonzero, read `arith pass` first — it is the only column that can be flatly wrong.

Caveat: on this corpus, `arith checked` reads 0 across all runners because these papers contain literature-comparison tables with quantity names like `Total biomass (g/L)` rather than aggregate-total rows or columns. This is not a failure of any runner; it is the honest outcome of a label-free metric on a corpus without checkable totals. The measurement weight falls to coverage, dropped pages, and cross-runner agreement.

Caveat: `order monotonic` is not evidence of correct reading order. It reads 1.000 for every runner because each runner already emits blocks in sorted order (the docling path sorts by page, top, left; the line-based runners bucket lines by rounded top), so asking whether sorted output is sorted always answers yes. `midword` is the weaker signal that actually varies.

Caveat: `sections/6` and the chunk columns compare within a runner family, not across. The docling runners supply their own `section_header` labels, while `pdfplumber` and `pdfjs-node` route all text through a font-blind classifier. Measured on one paper: docling found 5 of 6 canonical sections, pdfplumber 3, pdfjs 2 — reading that as "docling detects structure better" would be an artifact of the classifier, not a measurement.

Caveat: read `dropped pages` alongside `cov. mean-of-medians`, never that figure alone. Measured: `docling-default` had a median page ratio of 1.002 while its total characters were 0.909x the floor, because it lost one whole page rather than degrading uniformly. The mean-of-medians alone hides that entirely.

| runner | papers | cov. papers | cov. mean-of-medians | dropped pages | chars | order monotonic | midword | sections/6 | tables | empty cells | arith checked | arith pass | chunks | orphans | s/page |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `docling-default` | 47 | 47 | 1.047 | 15 | 2211634 | 1.000 | 2477 | 3.83 | 129 | 0.078 | 0 | — | 2763 | 336 | — |
| `docling-tuned` | 47 | 47 | 1.000 | 21 | 2108320 | 1.000 | 2735 | 3.94 | 128 | 0.076 | 0 | — | 2785 | 425 | 1.42 |
| `pdfjs-node` | 47 | 47 | 1.040 | 0 | 2265452 | 1.000 | 1038 | 2.89 | 0 | — | 0 | — | 2783 | 246 | 0.04 |
| `pdfplumber` | 47 | 47 | 1.000 | 0 | 2191495 | 1.000 | 1043 | 2.66 | 79 | 0.612 | 0 | — | 2822 | 263 | 0.09 |

## Cross-runner agreement

| pair | papers | mean of per-paper medians |
|---|---|---|
| docling-default vs docling-tuned | 47 | 0.904 |
| docling-default vs pdfjs-node | 47 | 0.909 |
| docling-default vs pdfplumber | 47 | 0.786 |
| docling-tuned vs pdfjs-node | 47 | 0.845 |
| docling-tuned vs pdfplumber | 47 | 0.735 |
| pdfjs-node vs pdfplumber | 47 | 0.842 |

## Worst five papers per runner, by coverage

- `docling-default`: Jovanovic et al. 2021 (part I) (0.833), Jiang et al. 2023 (0.975), Sheets et al. 2017 (0.979), Jovanovic et al 2021 (part II) (0.987), Methane Biocatalysis - Selecting the Right Microbe (0.987)
- `docling-tuned`: Patel et al. 2023 (0.744), Jovanovic et al. 2021 (part I) (0.859), Wohlgemuth et al. 2015 (0.902), A. Priyadarsini et al. 2023 (0.927), Xin et al. 2017 (0.934)
- `pdfjs-node`: Jovanovic et al. 2021 (part I) (0.94), Sahoo et al. 2022 (0.985), Takeguchi et al. 1997 (0.999), Wohlgemuth et al. 2015 (1.001), Hou et al. 1984 (1.001)
- `pdfplumber`: A. Priyadarsini et al. 2023 (1.0), Adegbola thesis High Density Cultures (1.0), Ahmadi & Lackner 2024 (1.0), Baldo et al. 2024 (1.0), Bjorck et al. 2018 (1.0)

## Chunk straddling

- `docling-default`: 0 chunks cross a section header; median chunk 958 chars
- `docling-tuned`: 0 chunks cross a section header; median chunk 903 chars
- `pdfjs-node`: 0 chunks cross a section header; median chunk 912 chars
- `pdfplumber`: 0 chunks cross a section header; median chunk 854 chars

## Findings

**The hosting question.** On the full 47-paper corpus, total characters extracted are: `pdfplumber` (floor) 2,191,495; `docling-default` 2,211,634 (1.009x the floor); `docling-tuned` 2,108,320 (0.962x the floor); `pdfjs-node` 2,265,452 (1.034x the floor). By the mean-of-per-paper-medians column, `pdfjs-node` sits at 1.040 against `docling-default`'s 1.047 and `docling-tuned`'s 1.000. Either way `pdfjs-node` is not behind either docling runner on coverage — it is at or slightly above both across the whole corpus, not just the earlier three-paper sample (which had shown docling-default noticeably below the floor; at 47 papers that direction reverses for `docling-default`, a reminder that a 3-paper sample was not representative). Cross-runner text agreement also puts `pdfjs-node` closer to the floor (`pdfjs-node` vs `pdfplumber` = 0.842) than `docling-default` is to the floor (`docling-default` vs `pdfplumber` = 0.786), which is expected: both `pdfjs-node` and `pdfplumber` read the embedded text layer directly, while both docling runners run a layout/OCR pipeline on top of it. On speed, `pdfjs-node` ran the full corpus at 0.04s/page against `docling-tuned`'s 1.42s/page — about 35x faster, not the roughly-20x seen on the earlier partial sample. On tables the answer is separate and blunt: `pdfjs-node` produced zero tables on all 47 papers, by construction, against 129 (`docling-default`), 128 (`docling-tuned`), and 79 (`pdfplumber`'s own naive detector). Verdict: for coverage, the zero-server browser-side design is not compromised by this data; for tables, it recovers none at all, so any product feature that depends on table structure cannot be served by `pdfjs-node` alone.

**Does `docling-tuned` beat `docling-default`?** No, on every axis measured. Coverage: total characters dropped from 2,211,634 to 2,108,320, a corpus-wide loss of 103,314 characters (-4.67%); the mean-of-medians column drops from 1.047 to 1.000 in the same direction. Dropped pages went up, not down: 15 under `docling-default` versus 21 under `docling-tuned`. Table count barely moved (129 vs 128) so tuning bought nothing there either. Broken out per paper: 43 of 47 papers lost characters under forced full-page OCR and only 4 gained. The single manifest-flagged scanned paper, `Xin et al. 2004`, gained 159 characters (+0.9%), consistent with the earlier partial measurement of +161 on that same paper. The worst born-digital loss was `Kim et al. 2021 - Biogas from Wastewater Sludge`, down 16,626 characters (-25.6%), followed by `Patel et al. 2023`, down 10,161 characters (-19.4%) — both larger than the -1,284/-8.2% loss seen on the earlier two-paper sample. Cost: `docling-tuned` ran the full corpus at 1.42s/page (about 13 minutes wall time for 602 pages) for a worse result than the free default. The earlier finding holds and strengthens at corpus scale: full-page OCR does not beat an embedded text layer here, and it actively hurts on born-digital PDFs, which are the overwhelming majority of this corpus (46 of 47 papers by the manifest's scanned-page heuristic).

**There was almost no tuning available.** On docling 2.60.0, `do_ocr`, `do_table_structure`, `TableFormerMode.ACCURATE`, `do_cell_matching`, and `generate_page_images=False` are already the library defaults — none of them is something `docling-tuned` turns on. The only genuine variable `docling-tuned` adds over `docling-default` is `force_full_page_ocr=True` (the explicit `DoclingParseV4DocumentBackend` is also today's default; it is pinned for version-bump protection, not because it changes behavior now). This pre-empts the plan's original idea of a pipeline-tuning effort: there was one knob, and turning it made results worse on 43 of 47 papers.

**Where all four runners disagree.** Excluding `Xin et al. 2004` (the 6-page scan whose non-OCR runners legitimately see 0 characters, which trivially produces 0.000 agreement against them), the paper with the lowest agreement across every runner pair is `Patel et al. 2023` (minimum pairwise per-paper-median agreement 0.457, mean across pairs 0.706); it is also independently `docling-tuned`'s single worst-coverage paper (0.744). Close behind: `Hamilton et al. 2024` (0.555) and `Jovanovic et al. 2021 (part I)` (0.558) — the latter also lands in the worst-five coverage list for three of the four runners independently (`docling-default` 0.833, `docling-tuned` 0.859, `pdfjs-node` 0.94), the strongest corroborated case of a genuinely hard PDF in this corpus. These three papers are worth opening by eye before trusting any single runner's output for them.

**What this lab cannot tell you.** There are no ground-truth labels anywhere in this corpus, so nothing above measures absolute correctness — only relative agreement and relative coverage against an arbitrary floor runner. `arith checked` reads 0 for every runner on all 47 papers: this corpus's tables are literature-comparison tables with per-row quantities, not tables with checkable totals, so the table-arithmetic metric found nothing to check here and is silent by construction, not because every runner got it right. `order monotonic` reads 1.000 for every runner for a structural reason, not a quality one: each runner already emits blocks pre-sorted, so the check answers "is sorted output sorted," which is always yes; it carries no discriminating signal on this corpus, and `midword` is the column that actually varies. Finally, the structural-hash reproduction check (below) came back MISMATCH on all three papers tested, which means this report's `docling-default` numbers should be read as v1's actual historical output, not as something a fresh docling-2.60.0 install here is currently able to regenerate byte-for-byte.
