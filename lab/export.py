"""Turn one runner's results into a bundle the static reader can load.

The one job that matters here: resolve `chunk["block_ids"]` into page
rectangles NOW, at build time, where the chunk and `blocks[]` are both in
hand. v1 shipped block references to the browser and spent three tiers of
fuzzy text matching trying to resolve them there.
"""
import hashlib
import json
import pathlib
import shutil


def chunk_regions(record, chunk):
    """[{page, rects: [[x0, top, x1, bottom], ...]}, ...] in page order.

    Grouped by page because a chunk can cross a page break inside a section.
    A block without a bbox contributes nothing rather than a guessed rect; a
    chunk whose blocks all lack geometry gets [], and the reader shows its
    text without a highlight.
    """
    blocks = record["blocks"]
    by_page = {}
    for block_id in chunk["block_ids"]:
        if not 0 <= block_id < len(blocks):
            continue
        block = blocks[block_id]
        if not block["bbox"]:
            continue
        by_page.setdefault(block["page"], []).append(list(block["bbox"]))
    return [{"page": page, "rects": by_page[page]} for page in sorted(by_page)]


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_bundle(records, entries, out_dir, corpus_dir, corpus_id=None, name=None):
    """Write manifest.json, papers.json, chunks.json and pdfs/ into out_dir.

    Returns the manifest dict. `vectors.bin` is Task 2's job and is added to
    the manifest by `lab.embed`, so a bundle written here is valid and simply
    has no semantic search.
    """
    out_dir = pathlib.Path(out_dir)
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)

    by_filename = {e["filename"]: e for e in entries}
    papers, chunks, missing = [], [], []
    for record in records:
        paper_id = record["paper_id"]
        entry = next((e for f, e in by_filename.items()
                      if pathlib.Path(f).stem == paper_id), None)
        if entry is None:
            continue
        papers.append({"paper_id": paper_id, "filename": entry["filename"],
                       "pages": entry["pages"], "sha256": entry["sha256"]})
        source = pathlib.Path(corpus_dir) / entry["filename"]
        if source.exists():
            shutil.copy2(source, out_dir / "pdfs" / entry["filename"])
        else:
            missing.append(entry["filename"])
        for chunk in record["chunks"]:
            chunks.append({
                "id": f"{paper_id}#{chunk['id']}",
                "paper_id": paper_id,
                "section": chunk["section"],
                "text": chunk["text"],
                "chars": chunk["chars"],
                "regions": chunk_regions(record, chunk),
            })

    files = {}
    for filename, payload in (("papers.json", papers), ("chunks.json", chunks)):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        (out_dir / filename).write_bytes(data)
        files[filename] = _sha256_bytes(data)

    first = records[0] if records else {}
    manifest = {
        "corpus_id": corpus_id or out_dir.name,
        "name": name or out_dir.name,
        "built_at": _now(),
        "source_runner": first.get("runner"),
        "runner_version": first.get("runner_version"),
        "embed_model": None,
        "dim": None,
        "counts": {"papers": len(papers), "chunks": len(chunks)},
        "files": files,
        "missing_pdfs": sorted(missing),
    }
    _write_manifest(out_dir, manifest)
    return manifest


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_manifest(out_dir, manifest):
    (pathlib.Path(out_dir) / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
