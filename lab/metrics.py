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
