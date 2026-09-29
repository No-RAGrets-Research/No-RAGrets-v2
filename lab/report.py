"""Aggregate per-paper results into results/REPORT.md.

Only aggregates are written. results/*.jsonl holds the full text of every paper
and stays gitignored — committing it would make this repo a dataset instead of
a tool.
"""
import json
import pathlib
import re
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


def _pooled_empty_cell_ratio(table_structures):
    """Empty cells over total cells, pooled across every paper's table.

    Averaging each paper's own ratio (mean-of-papers) weights a paper with one
    small table the same as a paper with forty large ones. Pooling weights by
    cell count instead, which is what "empty cells" should mean when read as
    a single number. On this corpus the two disagree materially (pdfplumber
    0.472 pooled vs 0.612 mean-of-papers), so pooling is the fix rather than
    just relabeling.
    """
    total_cells = sum(t["cells"] for t in table_structures if t["empty_cell_ratio"] is not None)
    if not total_cells:
        return None
    total_empty = sum(t["empty_cell_ratio"] * t["cells"]
                       for t in table_structures if t["empty_cell_ratio"] is not None)
    return total_empty / total_cells


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

        # Imported baselines carry wall_seconds == 0.0 by design (importing a
        # pre-existing JSON times no conversion). Render that as "no data"
        # rather than a flattering 0.00s/page. A runner with a mix of timed
        # and untimed papers keeps its mean; only the all-zero case goes dark.
        wall_seconds_values = [p["cost"]["wall_seconds"] for p in per_paper.values()]
        all_untimed = bool(wall_seconds_values) and all(w == 0 for w in wall_seconds_values)

        scored["runners"][runner] = {
            "papers": len(per_paper),
            "coverage": {
                # Coverage can only be computed for papers that also exist in
                # the floor runner's results, which may be fewer than "papers"
                # above. Recording it here lets the report show both counts
                # side by side instead of hiding the mismatch.
                "papers": len(covered),
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
                "empty_cell_ratio": _pooled_empty_cell_ratio(
                    [p["tables"] for p in per_paper.values()]),
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
                "seconds_per_page": None if all_untimed else
                    _mean([p["cost"]["seconds_per_page"] for p in per_paper.values()]),
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
        "When `arith checked` is nonzero, read `arith pass` first — it is the only "
        "column that can be flatly wrong.",
        "",
        "Caveat: on this corpus, `arith checked` reads 0 across all runners. These "
        "papers have no whole-cell total labels — a cell that is just `Total`, `Sum`, "
        "or `Overall`. Candidates such as `Total GWP 100` exist but are quantity names, "
        "not aggregate labels, and are not matched by design (matching them would "
        "silently sum unrelated columns beside them). This is not a failure of any "
        "runner; it is the honest outcome of a label-free metric on a corpus without "
        "checkable totals. The measurement weight falls to coverage and cross-runner "
        "agreement.",
        "",
        "Caveat: `order monotonic` still is not evidence of correct reading order, but it "
        "is no longer tautological for every runner. `pdfplumber` and `pdfjs-node` bucket "
        "lines by rounded top before emitting them, so their blocks are geometrically "
        "sorted by construction and this always reads 1.000 for them — asking whether "
        "sorted output is sorted always answers yes. `docling-default` and `docling-tuned` "
        "now keep docling's own `texts[]` order instead of being re-sorted geometrically "
        "(see Findings), so this column measures something real for them for the first "
        "time, and it is below 1.000 (0.919 / 0.960). Spot-checked on `A. Priyadarsini et "
        "al. 2023`: the backward jumps there are not clean two-column breaks — they are "
        "page furniture (footers, stray page-number glyphs) sitting between body text in "
        "`texts[]`, and this runner's own table-after-text placement (a table's visual "
        "position can be near the top of a page it is read after in full). `midword` "
        "remains the weaker, but real, per-block signal.",
        "",
        "Caveat: `sections/6` and the chunk columns compare within a runner family, not "
        "across. The docling runners supply their own `section_header` labels, while "
        "`pdfplumber` and `pdfjs-node` route all text through a font-blind classifier. "
        "Measured on one paper: docling found 5 of 6 canonical sections, pdfplumber 3, "
        "pdfjs 2 — reading that as \"docling detects structure better\" would be an "
        "artifact of the classifier, not a measurement.",
        "",
        "Caveat: `dropped pages` reads 0 for every runner on this corpus, and that is a "
        "fix, not a finding. Earlier, `chars_per_page` counted only paragraph, header, "
        "caption, and other text blocks — but a table block always carries `text: \"\"`, "
        "with its content in `tables[].cells` instead. Every page whose content was "
        "mostly a table therefore looked like a page where the runner lost content, "
        "which was the entire explanation for every dropped page any runner had shown. "
        "Table cells now count toward their own page (see Findings for the corrected "
        "totals), and the detector stays in the report because it would still catch a "
        "real regression — it simply has nothing to report on this corpus today.",
        "",
        "| runner | papers | cov. papers | cov. mean-of-medians | dropped pages | chars | "
        "order monotonic | midword | sections/6 | tables | empty cells (pooled) | arith checked | "
        "arith pass | chunks | orphans | s/page |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for runner, s in scored["runners"].items():
        lines.append(
            f"| `{runner}` | {s['papers']} | {s['coverage']['papers']} | "
            f"{_cell(s['coverage']['median_page_ratio'])} | "
            f"{s['coverage']['dropped_page_count']} | {s['coverage']['chars_total']} | "
            f"{_cell(s['reading_order']['monotonic_fraction'])} | "
            f"{s['reading_order']['blocks_ending_midword']} | "
            f"{_cell(s['structure']['found_exactly_once'], 2)} | {s['tables']['total']} | "
            f"{_cell(s['tables']['empty_cell_ratio'])} | {s['arithmetic']['checked']} | "
            f"{_cell(s['arithmetic']['pass_rate'])} | {s['chunks']['total']} | "
            f"{s['chunks']['orphan_chunks']} | {_cell(s['cost']['seconds_per_page'], 2)} |"
        )

    lines += ["", "## Cross-runner agreement", "",
              "| pair | papers | mean of per-paper medians |", "|---|---|---|"]
    for pair in scored["pairs"]:
        lines.append(f"| {pair['pair']} | {pair['papers']} | {_cell(pair['median_agreement'])} |")

    lines += ["", "## Worst five papers per runner, by coverage", ""]
    for runner, rows in scored["outliers"].items():
        listed = ", ".join(f"{r['paper_id']} ({r['median_page_ratio']})" for r in rows) or "—"
        lines.append(f"- `{runner}`: {listed}")

    lines += ["", "## Chunk straddling", "",
              "Caveat: this reads 0 for every runner by construction, not because "
              "chunking is safe in general. `chunk_blocks` flushes the buffer at "
              "every `section_header` block, so a chunk cannot straddle a header it "
              "would have to be built across in the first place. This metric cannot "
              "catch a straddling failure today; it exists to catch a regression if "
              "a future chunker stops flushing on headers.", ""]
    for runner, s in scored["runners"].items():
        median_chunk = _cell(s["chunks"]["median_chars"], 0)
        lines.append(f"- `{runner}`: {s['chunks']['straddling_chunks']} chunks cross a "
                      f"section header; median chunk {median_chunk} chars")
    lines.append("")
    return "\n".join(lines)


FINDINGS_RE = re.compile(r"^## Findings\b.*", re.S | re.M)


def write(floor=FLOOR_RUNNER):
    """Regenerate the generated tables/caveats, but keep the hand-written
    Findings section untouched.

    `compare` is meant to be re-run whenever results change, and doing so
    used to overwrite the whole file — including everything from `## Findings`
    onward, which is hand-written prose no runner regenerates. Preserving it
    means `compare` only ever replaces the parts it actually computed.
    """
    results = {runner: load_results(runner) for runner in available_runners()}
    results = {k: v for k, v in results.items() if v}
    if not results:
        raise SystemExit("no results found — run at least one runner first")
    scored = score(results, floor=floor)
    rendered = render(scored)
    RESULTS_DIR.mkdir(exist_ok=True)
    if REPORT_PATH.exists():
        match = FINDINGS_RE.search(REPORT_PATH.read_text())
        if match:
            rendered = rendered.rstrip("\n") + "\n\n" + match.group(0).rstrip("\n") + "\n"
    REPORT_PATH.write_text(rendered)
    return scored
