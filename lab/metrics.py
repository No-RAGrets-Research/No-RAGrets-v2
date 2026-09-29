"""Label-free metrics over the IR.

No ground truth exists for this corpus, so nothing here compares against a gold
standard. Every function either compares a runner to another runner, or checks
an internal consistency property that can be wrong on its own terms.

Never aggregate these into one score. v1 did that and produced a "96.45%" whose
formula was never written down.
"""
import re
import statistics

from lab import ir

# A page recovering less than this share of the floor runner's characters is
# treated as lost rather than merely worse. This is the issue #4357 detector.
DROPPED_PAGE_RATIO = 0.10

# Below this the floor runner found nothing itself, so there is no ratio to take.
FLOOR_MIN_CHARS = 50


def coverage(candidate, floor):
    """Characters per page as a share of the pdfplumber floor."""
    got = ir.chars_per_page(candidate)
    base = ir.chars_per_page(floor)
    ratios = {}
    dropped = []
    for page, floor_chars in base.items():
        if floor_chars < FLOOR_MIN_CHARS:
            continue
        ratio = got.get(page, 0) / floor_chars
        ratios[page] = ratio
        if ratio < DROPPED_PAGE_RATIO:
            dropped.append(page)
    return {
        "chars_total": sum(got.values()),
        "pages_compared": len(ratios),
        "median_page_ratio": statistics.median(ratios.values()) if ratios else None,
        "min_page_ratio": min(ratios.values()) if ratios else None,
        "dropped_pages": sorted(dropped),
        "dropped_page_count": len(dropped),
    }


NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _grams(text, size=3):
    flat = NON_ALNUM.sub(" ", text.lower()).strip()
    flat = re.sub(r"\s+", " ", flat)
    return {flat[i:i + size] for i in range(len(flat) - size + 1)}


def agreement(a, b):
    """Per-page character 3-gram Jaccard between two runners.

    Disagreement localises a conflict; coverage then says which runner lost it.
    """
    scores = {}
    for page in range(1, min(a["pages"], b["pages"]) + 1):
        left = _grams(ir.page_text(a, page))
        right = _grams(ir.page_text(b, page))
        union = left | right
        if not union:
            continue
        scores[page] = len(left & right) / len(union)
    worst = sorted(scores.items(), key=lambda kv: kv[1])[:5]
    return {
        "pair": f"{a['runner']} vs {b['runner']}",
        "pages_compared": len(scores),
        "median": statistics.median(scores.values()) if scores else None,
        "worst_pages": [{"page": p, "score": round(s, 3)} for p, s in worst],
    }


# A paragraph ending in a hyphen, or in a lowercase letter with no terminator,
# was almost certainly cut off mid-word or mid-sentence.
# Known ceiling: a paragraph legitimately ending in an abbreviation reads as
# truncated. It is a comparative signal across runners, not an absolute count.
TRUNCATED = re.compile(r"(-|[a-z])$")

# Blocks may sit slightly above the previous one on the same line without that
# being a reading-order failure.
SAME_LINE_SLACK = 2.0


def reading_order(candidate):
    """How often consecutive blocks move forward down the page."""
    boxed = [b for b in candidate["blocks"] if b["bbox"]]
    pairs = 0
    forward = 0
    for previous, current in zip(boxed, boxed[1:]):
        pairs += 1
        if current["page"] != previous["page"]:
            forward += 1 if current["page"] > previous["page"] else 0
            continue
        goes_down = current["bbox"][1] >= previous["bbox"][1] - SAME_LINE_SLACK
        goes_right = current["bbox"][0] > previous["bbox"][2]
        if goes_down or goes_right:
            forward += 1

    truncated = sum(
        1 for b in candidate["blocks"]
        if b["kind"] == "paragraph" and TRUNCATED.search(b["text"].strip())
    )
    return {
        "blocks": len(candidate["blocks"]),
        "blocks_with_bbox": len(boxed),
        "monotonic_fraction": (forward / pairs) if pairs else None,
        "blocks_ending_midword": truncated,
    }


SECTION_PATTERNS = {
    "abstract": re.compile(r"\babstract\b", re.I),
    "introduction": re.compile(r"\bintroduction\b", re.I),
    "methods": re.compile(r"\b(methods|methodology|materials and methods)\b", re.I),
    "results": re.compile(r"\bresults\b", re.I),
    "discussion": re.compile(r"\bdiscussion\b", re.I),
    "references": re.compile(r"\b(references|bibliography|literature cited)\b", re.I),
}


def structure_proxy(candidate):
    """Are the six sections a paper essentially always has each found once?

    A miss means the header was not detected, which downstream means the chunker
    had nothing to split on.
    """
    headers = [b["text"] for b in candidate["blocks"] if b["kind"] == "section_header"]
    counts = {
        name: sum(1 for header in headers if pattern.search(header))
        for name, pattern in SECTION_PATTERNS.items()
    }
    return {
        "section_headers": len(headers),
        "counts": counts,
        "found_exactly_once": sum(1 for n in counts.values() if n == 1),
        "missing": sorted(name for name, n in counts.items() if n == 0),
    }


def cost(candidate):
    """Wall clock. This is the issue #4174 detector."""
    pages = candidate["pages"]
    return {
        "wall_seconds": candidate["wall_seconds"],
        "seconds_per_page": (candidate["wall_seconds"] / pages) if pages else None,
    }


# ------------------------------------------------------------------- tables

TOTAL_WORD = re.compile(r"\b(total|totals|sum|sums|overall)\b", re.I)

# 1% relative, or 0.01 absolute when the total is near zero. Papers round their
# own published totals, so a tighter tolerance would fail on correct tables.
TOLERANCE_RELATIVE = 0.01
TOLERANCE_ABSOLUTE = 0.01

# Row 0 is assumed to be a header row, and column 0 a label column.
# Known ceiling: a table with two header rows will have its first data row read
# as a header and excluded from the sum. Upgrade path is detecting header depth
# by numeric density per row.
HEADER_ROWS = 1
LABEL_COLS = 1


def parse_number(raw):
    """Parse the number formats papers actually print, or return None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("%", "").replace(" ", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "")
    if text in ("", "-", "."):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _total_series(table):
    """Yield every (values, total) pair a labelled total row or column implies."""
    cells, rows, cols = table["cells"], table["rows"], table["cols"]

    for r in range(HEADER_ROWS, rows):
        labels = [cells[r][c] or "" for c in range(min(LABEL_COLS + 1, cols))]
        if not any(TOTAL_WORD.search(label) for label in labels):
            continue
        for c in range(cols):
            total = parse_number(cells[r][c])
            values = [v for v in (parse_number(cells[i][c]) for i in range(HEADER_ROWS, r))
                      if v is not None]
            if total is None or len(values) < 2:
                continue
            yield {"axis": "row", "row": r, "col": c, "values": values, "total": total}

    for c in range(LABEL_COLS, cols):
        labels = [cells[r][c] or "" for r in range(min(HEADER_ROWS + 1, rows))]
        if not any(TOTAL_WORD.search(label) for label in labels):
            continue
        for r in range(rows):
            total = parse_number(cells[r][c])
            values = [v for v in (parse_number(cells[r][i]) for i in range(LABEL_COLS, c))
                      if v is not None]
            if total is None or len(values) < 2:
                continue
            yield {"axis": "col", "row": r, "col": c, "values": values, "total": total}


def table_arithmetic(candidate):
    """Does a labelled total actually equal the sum of its series?

    The only metric here that can be flatly right or wrong with no labels, so it
    carries the most weight in the report. A misread cell, a dropped row, or a
    column shifted by one all show up as a failure.
    """
    checked = 0
    passed = 0
    failures = []
    for index, table in enumerate(candidate["tables"]):
        for series in _total_series(table):
            total = series["total"]
            checked += 1
            limit = max(abs(total) * TOLERANCE_RELATIVE, TOLERANCE_ABSOLUTE)
            if abs(sum(series["values"]) - total) <= limit:
                passed += 1
            elif len(failures) < 20:
                failures.append({
                    "table": index, "page": table["page"], "axis": series["axis"],
                    "row": series["row"], "col": series["col"],
                    "summed": round(sum(series["values"]), 4), "printed": total,
                })
    return {
        "checked": checked,
        "passed": passed,
        "pass_rate": (passed / checked) if checked else None,
        "failures": failures,
    }


NUMERIC_CELL = re.compile(r"\d")


def table_structure(candidate):
    """Table count and cell density.

    Rectangularity is deliberately not measured: ir.validate rejects a ragged
    table and the runners pad short rows, so it would read 1.0 for every runner.
    Empty-cell density catches the same failure — a misread grid — and can vary.
    """
    tables = candidate["tables"]
    total_cells = sum(t["rows"] * t["cols"] for t in tables)
    if not tables or not total_cells:
        return {
            "tables": len(tables), "cells": total_cells,
            "empty_cell_ratio": None, "numeric_cell_ratio": None,
            "median_rows": None, "median_cols": None,
        }
    flat = [cell for t in tables for row in t["cells"] for cell in row]
    empty = sum(1 for cell in flat if not (cell or "").strip())
    numeric = sum(1 for cell in flat if NUMERIC_CELL.search(cell or ""))
    return {
        "tables": len(tables),
        "cells": total_cells,
        "empty_cell_ratio": empty / len(flat),
        "numeric_cell_ratio": numeric / len(flat),
        "median_rows": statistics.median([t["rows"] for t in tables]),
        "median_cols": statistics.median([t["cols"] for t in tables]),
    }


# ------------------------------------------------------------------- chunks

ORPHAN_CHARS = 100


def chunk_health(candidate):
    """Are the chunks something a retriever could use?"""
    chunks = candidate["chunks"]
    if not chunks:
        return {
            "chunks": 0, "median_chars": None, "p10_chars": None, "p90_chars": None,
            "orphan_chunks": 0, "midsentence_starts": 0, "straddling_chunks": 0,
        }

    sizes = sorted(c["chars"] for c in chunks)
    header_orders = {b["order"] for b in candidate["blocks"] if b["kind"] == "section_header"}

    def straddles(chunk):
        ids = chunk.get("block_ids") or []
        if len(ids) < 2:
            return False
        low, high = min(ids), max(ids)
        return any(low < order < high for order in header_orders)

    def quantile(fraction):
        return sizes[min(len(sizes) - 1, int(fraction * len(sizes)))]

    return {
        "chunks": len(chunks),
        "median_chars": statistics.median(sizes),
        "p10_chars": quantile(0.10),
        "p90_chars": quantile(0.90),
        "orphan_chunks": sum(1 for c in chunks if c["chars"] < ORPHAN_CHARS),
        "midsentence_starts": sum(1 for c in chunks if c["text"][:1].islower()),
        "straddling_chunks": sum(1 for c in chunks if straddles(c)),
    }
