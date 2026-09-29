"""The IR every runner emits and every metric consumes.

This is the interface the UI, RAG and anomaly-detection parts of No RAGrets v2
will depend on, so a change here is a breaking change for the whole project.

Shape:
    {paper_id, runner, runner_version, pdf_sha256, pages, wall_seconds,
     blocks: [{page, kind, text, bbox|null, order}],
     tables: [{page, rows, cols, cells, caption|null}],
     chunks: [{id, text, block_ids, section, chars}]}

`bbox` is [x0, top, x1, bottom] in top-down page coordinates, or null for
runners that cannot supply it. `order` is the block's index in reading order
and is what `chunk.block_ids` refers to.
"""
import hashlib
import json

BLOCK_KINDS = {"paragraph", "section_header", "table", "caption", "other"}

IR_FIELDS = (
    "paper_id", "runner", "runner_version", "pdf_sha256",
    "pages", "wall_seconds", "blocks", "tables", "chunks",
)

# Everything except timing, so two runs of one runner over one PDF compare
# byte for byte.
HASHED_FIELDS = tuple(f for f in IR_FIELDS if f != "wall_seconds")

TEXT_KINDS = {"paragraph", "section_header", "caption", "other"}


def validate(ir):
    """Raise ValueError on anything a metric could not read. Returns ir."""
    for field in IR_FIELDS:
        if field not in ir:
            raise ValueError(f"missing field: {field}")
    if not isinstance(ir["pages"], int) or ir["pages"] < 1:
        raise ValueError(f"pages must be a positive int, got {ir['pages']!r}")

    for i, b in enumerate(ir["blocks"]):
        if b.get("kind") not in BLOCK_KINDS:
            raise ValueError(f"block {i}: unknown kind {b.get('kind')!r}")
        if not isinstance(b.get("text"), str):
            raise ValueError(f"block {i}: text must be a str")
        if not isinstance(b.get("page"), int) or b["page"] < 1:
            raise ValueError(f"block {i}: page must be a positive int")
        if not isinstance(b.get("order"), int):
            raise ValueError(f"block {i}: order must be an int")
        bbox = b.get("bbox", "missing")
        if bbox == "missing":
            raise ValueError(f"block {i}: bbox key required (use null if unavailable)")
        if bbox is not None:
            if len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
                raise ValueError(f"block {i}: bbox must be null or four numbers")

    orders = [b["order"] for b in ir["blocks"]]
    if orders != sorted(orders):
        raise ValueError("blocks must be sorted by order")

    for i, t in enumerate(ir["tables"]):
        for key in ("page", "rows", "cols"):
            if not isinstance(t.get(key), int):
                raise ValueError(f"table {i}: {key} must be an int")
        cells = t.get("cells")
        if not isinstance(cells, list) or len(cells) != t["rows"]:
            raise ValueError(f"table {i}: cells has {len(cells or [])} rows, rows says {t['rows']}")
        for r, row in enumerate(cells):
            if len(row) != t["cols"]:
                raise ValueError(f"table {i} row {r}: {len(row)} cells, cols says {t['cols']}")

    known_orders = set(orders)
    for i, c in enumerate(ir["chunks"]):
        if not isinstance(c.get("text"), str):
            raise ValueError(f"chunk {i}: text must be a str")
        if c.get("chars") != len(c["text"]):
            raise ValueError(f"chunk {i}: chars={c.get('chars')} but text is {len(c['text'])} long")
        for bid in c.get("block_ids", []):
            if bid not in known_orders:
                raise ValueError(f"chunk {i}: block_id {bid} matches no block order")
    return ir


def content_hash(ir):
    """Stable sha256 over everything but timing."""
    payload = {k: ir[k] for k in HASHED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def chars_per_page(ir):
    """Text characters recovered per page. Tables carry no text of their own."""
    counts = {p: 0 for p in range(1, ir["pages"] + 1)}
    for b in ir["blocks"]:
        if b["kind"] in TEXT_KINDS:
            counts[b["page"]] = counts.get(b["page"], 0) + len(b["text"])
    return counts


def page_text(ir, page):
    return " ".join(
        b["text"] for b in ir["blocks"]
        if b["page"] == page and b["kind"] in TEXT_KINDS
    )
