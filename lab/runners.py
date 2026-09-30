"""The four runners, and the helpers they share.

Every runner ends by calling finish(), which applies the one chunker. That is
what holds chunking constant so extraction is the only variable.
"""
import json
import pathlib
import re
import statistics
import subprocess
import time

from lab import ir

RUNNERS = {}


def runner(name):
    def register(fn):
        RUNNERS[name] = fn
        return fn
    return register


# ---------------------------------------------------------------- classification

CANONICAL_SECTIONS = (
    "abstract", "introduction", "background", "methods", "materials and methods",
    "method", "results", "results and discussion", "discussion", "conclusion",
    "conclusions", "references", "acknowledgements", "acknowledgments",
)

CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|table|scheme|plate)\s*\d+", re.I)
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(\.\d+)*)[.)]?\s+(?P<rest>[A-Za-z].*)$")


def classify(text):
    """Header / caption / paragraph from the text alone.

    Known ceiling: no font-size or boldness signal, because two of the four
    runners do not expose it. An all-caps figure caption could read as a header.
    Upgrade path is passing per-line font size through the line dicts.
    """
    stripped = text.strip()
    if not stripped:
        return "other"
    if CAPTION_RE.match(stripped):
        return "caption"

    candidate = stripped
    numbered = NUMBERED_HEADING_RE.match(stripped)
    if numbered:
        candidate = numbered.group("rest")

    bare = candidate.rstrip(":.").strip()
    if bare.lower() in CANONICAL_SECTIONS:
        return "section_header"
    words = bare.split()
    if numbered and len(words) <= 8 and not bare.endswith("."):
        return "section_header"
    if len(words) <= 6 and bare.isupper() and len(bare) > 2:
        return "section_header"
    return "paragraph"


# ------------------------------------------------------------- line -> paragraph

def group_lines(lines):
    """Join lines into paragraph-ish blocks on vertical gaps.

    Runners that emit lines (pdfplumber, pdfjs) go through this so their block
    granularity matches Docling's. Without it, the reading-order metric would
    measure block size rather than extraction quality.
    """
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return []

    heights = [l["bbox"][3] - l["bbox"][1] for l in lines if l["bbox"]]
    typical = statistics.median(heights) if heights else 10.0
    gap_limit = 1.6 * typical

    groups = [[lines[0]]]
    for previous, current in zip(lines, lines[1:]):
        gap = current["bbox"][1] - previous["bbox"][3] if (previous["bbox"] and current["bbox"]) else 0
        starts_new = (
            gap > gap_limit
            or classify(current["text"]) != "paragraph"
            or classify(previous["text"]) != "paragraph"
        )
        if starts_new:
            groups.append([current])
        else:
            groups[-1].append(current)

    blocks = []
    for group in groups:
        text = _join_lines([l["text"] for l in group])
        boxes = [l["bbox"] for l in group if l["bbox"]]
        bbox = None
        if boxes:
            bbox = [
                min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes),
            ]
        blocks.append({"kind": classify(text), "text": text, "bbox": bbox})
    return blocks


def _join_lines(texts):
    out = ""
    for text in texts:
        piece = text.strip()
        if not out:
            out = piece
        elif out.endswith("-"):
            out = out[:-1] + piece      # de-hyphenate a wrapped word
        else:
            out = out + " " + piece
    return out


# -------------------------------------------------------------------- chunking

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
CHUNK_BUDGET = 1200


def split_sentences(text):
    """Regex sentence splitting.

    Known ceiling: splits on "et al. 1984" and other abbreviations. Upgrade path
    is swapping this one function for spaCy if chunk-health numbers turn out to
    be dominated by split noise rather than extraction quality.
    """
    return [s.strip() for s in SENTENCE_BOUNDARY.split(text) if s.strip()]


CHUNKABLE = {"paragraph", "caption", "other"}


def chunk_blocks(blocks, budget=CHUNK_BUDGET):
    """Split on section headers, then pack to a character budget on sentence
    boundaries."""
    chunks = []
    section = "(front matter)"
    buffer = []
    block_ids = []

    def flush():
        nonlocal buffer, block_ids
        text = " ".join(buffer).strip()
        if text:
            chunks.append({
                "id": len(chunks), "text": text, "block_ids": list(block_ids),
                "section": section, "chars": len(text),
            })
        buffer = []
        block_ids = []

    for block in blocks:
        if block["kind"] == "section_header":
            flush()
            section = block["text"].strip() or section
            continue
        if block["kind"] not in CHUNKABLE:
            continue
        for sentence in split_sentences(block["text"]):
            used = len(" ".join(buffer))
            if buffer and used + len(sentence) + 1 > budget:
                flush()
            buffer.append(sentence)
            if block["order"] not in block_ids:
                block_ids.append(block["order"])
    flush()
    return chunks


# ---------------------------------------------------------------------- finish

def finish(paper_id, runner_name, runner_version, sha256, pages, wall_seconds, blocks, tables):
    """Number the blocks, chunk them, validate, return the IR."""
    for index, block in enumerate(blocks):
        block["order"] = index
        block.setdefault("bbox", None)
    return ir.validate({
        "paper_id": paper_id,
        "runner": runner_name,
        "runner_version": runner_version,
        "pdf_sha256": sha256,
        "pages": pages,
        "wall_seconds": round(wall_seconds, 3),
        "blocks": blocks,
        "tables": tables,
        "chunks": chunk_blocks(blocks),
    })


# ------------------------------------------------------------ pdfplumber floor

def _pdfplumber_lines(page, tolerance=2.0):
    rows = {}
    for word in page.extract_words():
        rows.setdefault(round(word["top"] / tolerance), []).append(word)
    lines = []
    for key in sorted(rows):
        words = sorted(rows[key], key=lambda w: w["x0"])
        lines.append({
            "text": " ".join(w["text"] for w in words),
            "bbox": [
                min(w["x0"] for w in words), min(w["top"] for w in words),
                max(w["x1"] for w in words), max(w["bottom"] for w in words),
            ],
        })
    return lines


@runner("pdfplumber")
def run_pdfplumber(pdf_path, paper_id, sha256):
    """The floor. MIT-licensed, no OCR, no ML — whatever a plain text layer gives."""
    import pdfplumber

    started = time.time()
    blocks = []
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables()  # a page pdfminer cannot parse yields no tables
            except Exception:
                raw_tables = []
            for raw in raw_tables:
                rows = [[(cell or "").strip() for cell in row] for row in raw]
                cols = max((len(row) for row in rows), default=0)
                rows = [row + [""] * (cols - len(row)) for row in rows]
                if not rows or not cols:
                    continue
                tables.append({
                    "page": number, "rows": len(rows), "cols": cols,
                    "cells": rows, "caption": None,
                })
                blocks.append({"page": number, "kind": "table", "text": "", "bbox": None})
            try:
                lines = _pdfplumber_lines(page)  # a page pdfminer cannot parse yields no lines
            except Exception:
                lines = []
            for block in group_lines(lines):
                block["page"] = number
                blocks.append(block)

    return finish(
        paper_id, "pdfplumber", _version("pdfplumber"), sha256,
        page_count, time.time() - started, blocks, tables,
    )


def _version(package):
    from importlib.metadata import version
    try:
        return f"{package}=={version(package)}"
    except Exception:
        return f"{package}==unknown"


# ------------------------------------------------------------------- docling

# DoclingDocument labels -> our block kinds.
DOCLING_LABEL_KIND = {
    "title": "section_header",
    "section_header": "section_header",
    "caption": "caption",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "paragraph",
    "footnote": "other",
    "page_header": "other",
    "page_footer": "other",
    "formula": "other",
    "code": "other",
    "reference": "paragraph",
}


def _page_heights(doc):
    pages = doc.get("pages") or {}
    if isinstance(pages, dict):
        items = pages.values()
    else:
        items = pages
    heights = {}
    for page in items:
        number = page.get("page_no")
        size = page.get("size") or {}
        if number is not None:
            heights[int(number)] = float(size.get("height") or 0.0)
    return heights


def _docling_prov(item, heights):
    """Return (page, bbox) with bbox in top-down coordinates, or (None, None).

    Docling reports bottom-left origin by default: t is the distance from the
    bottom, so it must be flipped or every reading-order number is inverted.
    """
    prov = (item.get("prov") or [None])[0]
    if not prov:
        return None, None
    page = prov.get("page_no")
    box = prov.get("bbox") or {}
    if not box or page is None:
        return page, None
    left, right = box.get("l"), box.get("r")
    top, bottom = box.get("t"), box.get("b")
    if None in (left, right, top, bottom):
        return page, None
    if (box.get("coord_origin") or "BOTTOMLEFT").upper() == "BOTTOMLEFT":
        height = heights.get(int(page), 0.0)
        if not height:
            # Without the page height there is no coordinate frame to flip
            # into, so the honest answer is no bbox.
            return page, None
        top, bottom = height - top, height - bottom
    if top > bottom:
        top, bottom = bottom, top
    return page, [float(left), float(top), float(right), float(bottom)]


def _docling_cells(data):
    grid = data.get("grid")
    if grid:
        return [[(cell or {}).get("text", "") or "" for cell in row] for row in grid]

    cells = data.get("table_cells") or []
    rows = data.get("num_rows") or max((c.get("end_row_offset_idx", 0) for c in cells), default=0)
    cols = data.get("num_cols") or max((c.get("end_col_offset_idx", 0) for c in cells), default=0)
    grid = [[""] * cols for _ in range(rows)]
    for cell in cells:
        r = cell.get("start_row_offset_idx", 0)
        c = cell.get("start_col_offset_idx", 0)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = cell.get("text", "") or ""
    return grid


def ir_from_docling_dict(doc, paper_id, sha256, wall_seconds, runner_name, runner_version):
    """Build the IR, preserving docling's own reading order.

    Docling's `texts[]` is already in reading order (that is what
    DoclingDocument means by the list). Re-sorting it geometrically by
    (top, left) looks reasonable but is wrong on any multi-column page: it
    interleaves columns whenever one column's lower block sits above the
    other column's upper block, destroying the order docling supplied. So
    the only sort here is a *stable* one on page number, keeping each text's
    original `texts[]` index as the tiebreaker. Table blocks carry no
    chunkable text of their own (`kind == "table"`, `text == ""`), so they
    are placed after that page's text blocks — the same placement already
    used for the pdfplumber runner, which appends a page's tables before its
    text lines.

    A `body.children` tree walk was considered instead and rejected: captions
    hang off their table's `captions` ref rather than `body`, and headers and
    footers live under `furniture`, so walking `body` alone silently drops
    many texts that `texts[]` still has.
    """
    heights = _page_heights(doc)
    by_ref = {t.get("self_ref"): (t.get("text") or "") for t in doc.get("texts") or []}

    items = []
    for index, text_item in enumerate(doc.get("texts") or []):
        page, bbox = _docling_prov(text_item, heights)
        body = text_item.get("text") or ""
        if not body.strip() or page is None:
            continue
        kind = DOCLING_LABEL_KIND.get(text_item.get("label"), "other")
        if kind == "paragraph":
            # Docling labels many headers plainly "text"; re-check by content.
            kind = classify(body)
        block = {"page": int(page), "kind": kind, "text": body, "bbox": bbox}
        items.append((int(page), 0, index, block))

    tables = []
    for index, table_item in enumerate(doc.get("tables") or []):
        page, bbox = _docling_prov(table_item, heights)
        if page is None:
            continue
        cells = _docling_cells(table_item.get("data") or {})
        cols = max((len(row) for row in cells), default=0)
        cells = [row + [""] * (cols - len(row)) for row in cells]
        caption_refs = table_item.get("captions") or []
        caption = next((by_ref.get(r.get("$ref")) for r in caption_refs if r.get("$ref") in by_ref), None)
        tables.append({
            "page": int(page), "rows": len(cells), "cols": cols,
            "cells": cells, "caption": caption,
        })
        block = {"page": int(page), "kind": "table", "text": "", "bbox": bbox}
        # is_table=1 sorts after this page's text blocks (is_table=0).
        items.append((int(page), 1, index, block))

    items.sort(key=lambda entry: entry[:3])
    blocks = [entry[3] for entry in items]
    pages = max(heights) if heights else max((b["page"] for b in blocks), default=1)
    return finish(paper_id, runner_name, runner_version, sha256,
                  int(pages), wall_seconds, blocks, tables)


def import_docling_json(json_path, paper_id, sha256):
    """Import a DoclingDocument JSON produced earlier by a bare DocumentConverter.

    This is how the baseline costs zero compute: the 47 files in
    No-RAGrets-Master/data/docling_json/ came from
    pipeline/kg_gen_pipeline/core/pdf_converter.py:44 at docling 2.60.0.
    wall_seconds is 0.0 because the conversion is not being timed here.
    """
    doc = json.loads(pathlib.Path(json_path).read_text())
    return ir_from_docling_dict(doc, paper_id, sha256, 0.0,
                                "docling-default", "docling==2.60.0 (imported)")


@runner("docling-default")
def run_docling_default(pdf_path, paper_id, sha256):
    """Exactly what v1 ran: bare DocumentConverter(), every option default."""
    from docling.document_converter import DocumentConverter

    started = time.time()
    result = DocumentConverter().convert(str(pdf_path))
    doc = result.document.export_to_dict()
    return ir_from_docling_dict(doc, paper_id, sha256, time.time() - started,
                                "docling-default", _version("docling"))


def tuned_converter():
    """OCR every page, accurate table structure, backend pinned explicitly.

    On docling 2.60.0, do_ocr, do_table_structure, the accurate table mode,
    do_cell_matching, and generate_page_images=False are already the defaults.
    The one genuine variable this runner adds is force_full_page_ocr=True:
    it OCRs every page instead of trusting the PDF's embedded text layer,
    which is the only OCR question still open on a corpus that is mostly
    born-digital (median 4178 chars/page) with one fully scanned paper.

    The explicit backend is not optional, but it is not a downgrade either:
    DoclingParseV4DocumentBackend is also today's default. Naming it here is
    version-bump protection, not a change of parser. Docling 2.123.0 made
    threaded docling-parse the default (PR #3764), which is what drops most
    of a scanned PDF's OCR text layer (issue #4357) and runs ~4x slower on
    CPU (issue #4174) -- both still open on 2026-09-28. Passing the backend
    explicitly means this runner keeps using the parser we chose even if
    that default changes out from under us.
    """
    from docling.backend.docling_parse_v4_backend import DoclingParseV4DocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.generate_page_images = False   # nothing here looks at images
    options.ocr_options.force_full_page_ocr = True

    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=options,
            backend=DoclingParseV4DocumentBackend,
        )
    })


def _ocr_engine_suffix():
    """Which engine OcrAutoOptions actually resolves to on this machine.

    docling's OcrAutoModel tries ocrmac first on darwin, falling back to
    rapidocr (onnxruntime backend) elsewhere or if ocrmac is not installed.
    Recording the resolved engine in runner_version matters because the two
    produce different text and wildly different timings: a "docling-tuned"
    result from this machine is not comparable to one from Linux CI without
    knowing which engine actually ran.
    """
    import sys

    if sys.platform == "darwin":
        try:
            import ocrmac  # noqa: F401
            return "+ocrmac"
        except ImportError:
            pass
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
        return "+rapidocr"
    except ImportError:
        pass
    return "+ocr-unknown"


def _docling_tuned_version():
    return _version("docling") + _ocr_engine_suffix()


@runner("docling-tuned")
def run_docling_tuned(pdf_path, paper_id, sha256):
    started = time.time()
    result = tuned_converter().convert(str(pdf_path))
    doc = result.document.export_to_dict()
    return ir_from_docling_dict(doc, paper_id, sha256, time.time() - started,
                                "docling-tuned", _docling_tuned_version())


# ----------------------------------------------------------------- pdfjs-node

PDFJS_SCRIPT = pathlib.Path(__file__).parent / "pdfjs_runner.mjs"


@runner("pdfjs-node")
def run_pdfjs(pdf_path, paper_id, sha256):
    """The extractor the shipped app would use: pdf.js, in Node instead of a browser.

    Emits no tables at all — pdf.js has no table model. That is a real capability
    difference and the table metrics are what will price it.
    """
    started = time.time()
    finished = subprocess.run(
        ["node", str(PDFJS_SCRIPT), str(pdf_path)],
        capture_output=True, text=True, check=False,
    )
    if finished.returncode != 0:
        raise RuntimeError(f"pdfjs_runner.mjs exited {finished.returncode}: {finished.stderr[-500:]}")
    payload = json.loads(finished.stdout)

    blocks = []
    for page in payload["pages"]:
        for block in group_lines(page["lines"]):
            block["page"] = int(page["page"])
            blocks.append(block)

    return finish(paper_id, "pdfjs-node", _pdfjs_version(), sha256,
                  len(payload["pages"]), time.time() - started, blocks, [])


def _pdfjs_version():
    try:
        package = json.loads(pathlib.Path("node_modules/pdfjs-dist/package.json").read_text())
        return f"pdfjs-dist=={package['version']}"
    except Exception:
        return "pdfjs-dist==unknown"


# The runner_version a fresh run would produce right now, without actually
# running the extractor. cmd_run uses this to detect a library upgrade (e.g.
# a docling bump, or an OCR engine change) and refuse a stale cache hit.
RUNNER_VERSIONS = {
    "pdfplumber": lambda: _version("pdfplumber"),
    "docling-default": lambda: _version("docling"),
    "docling-tuned": _docling_tuned_version,
    "pdfjs-node": _pdfjs_version,
}
