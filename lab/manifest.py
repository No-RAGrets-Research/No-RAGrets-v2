"""The corpus lives outside the repo. The manifest is how a run proves it is
looking at the same papers as the last run.

This exists because of a real failure in v1: data/docling_json/ holds 49 JSON
files for 47 PDFs, because its cache was a filename-stem existence check with
no content hash and no version awareness.
"""
import hashlib
import json
import os
import pathlib

MANIFEST_PATH = pathlib.Path("corpus.manifest.json")

# A born-digital page carries far more than this. Below it, the page is either
# a scan with no OCR layer or a scan whose OCR layer is broken.
# Known ceiling: a genuinely sparse page (a full-page figure) reads as scanned.
SCANNED_CHARS_PER_PAGE = 200


def corpus_dir():
    raw = os.environ.get("NORAGRETS_CORPUS")
    if not raw:
        raise SystemExit("set NORAGRETS_CORPUS to the directory holding the PDFs")
    path = pathlib.Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit(f"NORAGRETS_CORPUS is not a directory: {path}")
    return path


def pdf_paths(directory=None):
    directory = directory or corpus_dir()
    return sorted(p for p in directory.iterdir() if p.suffix.lower() == ".pdf")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(path):
    """One manifest entry. Opens the PDF once with pdfplumber for page count
    and text-layer size."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        chars = 0
        for page in pdf.pages:
            try:
                chars += len(page.extract_text() or "")
            except Exception:
                pass    # a page pdfminer cannot parse is indistinguishable from zero text layer
    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "pages": pages,
        "chars_text_layer": chars,
        "scanned": pages > 0 and (chars / pages) < SCANNED_CHARS_PER_PAGE,
        "doi": None,
    }


def build(directory=None):
    entries = [describe(p) for p in pdf_paths(directory)]
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
    return entries


def load():
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"{MANIFEST_PATH} not found — run: python -m lab manifest build")
    return json.loads(MANIFEST_PATH.read_text())


def verify(entries=None, directory=None):
    """Compare the manifest against what is actually on disk."""
    entries = load() if entries is None else entries
    directory = directory or corpus_dir()
    on_disk = {p.name: p for p in pdf_paths(directory)}
    expected = {e["filename"]: e for e in entries}

    missing = sorted(set(expected) - set(on_disk))
    extra = sorted(set(on_disk) - set(expected))
    changed = sorted(
        name for name in set(expected) & set(on_disk)
        if sha256_file(on_disk[name]) != expected[name]["sha256"]
    )
    return {
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "ok": not (missing or extra or changed),
    }


def entry_for(filename, entries=None):
    entries = load() if entries is None else entries
    for e in entries:
        if e["filename"] == filename:
            return e
    raise SystemExit(f"{filename} is not in {MANIFEST_PATH} — rebuild the manifest")
