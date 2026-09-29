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
        "When `arith checked` is nonzero, read `arith pass` first — it is the only "
        "column that can be flatly wrong.",
        "",
        "Caveat: on this corpus, `arith checked` reads 0 across all runners because "
        "these papers contain literature-comparison tables with quantity names like "
        "`Total biomass (g/L)` rather than aggregate-total rows or columns. This is not "
        "a failure of any runner; it is the honest outcome of a label-free metric on a "
        "corpus without checkable totals. The measurement weight falls to coverage, "
        "dropped pages, and cross-runner agreement.",
        "",
        "Caveat: `order monotonic` is not evidence of correct reading order. It reads 1.000 "
        "for every runner because each runner already emits blocks in sorted order (the "
        "docling path sorts by page, top, left; the line-based runners bucket lines by "
        "rounded top), so asking whether sorted output is sorted always answers yes. "
        "`midword` is the weaker signal that actually varies.",
        "",
        "Caveat: `sections/6` and the chunk columns compare within a runner family, not "
        "across. The docling runners supply their own `section_header` labels, while "
        "`pdfplumber` and `pdfjs-node` route all text through a font-blind classifier. "
        "Measured on one paper: docling found 5 of 6 canonical sections, pdfplumber 3, "
        "pdfjs 2 — reading that as \"docling detects structure better\" would be an "
        "artifact of the classifier, not a measurement.",
        "",
        "Caveat: read `dropped pages` alongside `cov. median`, never the median alone. "
        "Measured: `docling-default` had a median page ratio of 1.002 while its total "
        "characters were 0.909x the floor, because it lost one whole page rather than "
        "degrading uniformly. The median alone hides that entirely.",
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
