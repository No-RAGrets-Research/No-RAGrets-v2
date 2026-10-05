"""One-off check: do the bundle's chunk rectangles sit on the right text?

Not a test. A green rect-transform unit test cannot see a rotated page or a
cropbox offset; a human looking at three PNGs can. Run it once after a bundle
is built, and again if the geometry code ever changes.

    ./.venv/bin/python tools/verify_highlights.py bundles/no-ragrets-47
"""
import json
import pathlib
import sys

import pdfplumber

# One two-column paper (the report's own gutter-span example), one thesis with
# many tables, one ordinary article.
WANTED = ["A. Priyadarsini et al. 2023", "Adegbola thesis High Density Cultures",
          "Ahmadi & Lackner 2024"]
OUT_DIR = pathlib.Path("/tmp/noragrets-highlight-check")


def main(bundle_dir):
    bundle = pathlib.Path(bundle_dir)
    chunks = json.loads((bundle / "chunks.json").read_text())
    papers = {p["paper_id"]: p for p in json.loads((bundle / "papers.json").read_text())}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for paper_id in WANTED:
        paper = papers.get(paper_id)
        if paper is None:
            print(f"SKIP   {paper_id}: not in this bundle")
            continue
        # The longest chunk with geometry: the biggest target to judge by eye.
        candidates = [c for c in chunks if c["paper_id"] == paper_id and c["regions"]]
        if not candidates:
            print(f"SKIP   {paper_id}: no chunk carries geometry")
            continue
        chunk = max(candidates, key=lambda c: c["chars"])
        region = chunk["regions"][0]

        pdf_path = bundle / "pdfs" / paper["filename"]
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[region["page"] - 1]
            image = page.to_image(resolution=100)
            image.draw_rects(region["rects"], stroke="red", stroke_width=2)
            out = OUT_DIR / f"{paper_id.replace('/', '-')}-p{region['page']}.png"
            image.save(out)

        print(f"WROTE  {out}")
        print(f"       page {region['page']}, {len(region['rects'])} rect(s)")
        print(f"       chunk text starts: {chunk['text'][:90]!r}")
    print(f"\nOpen the PNGs and check the red rectangles sit on that text:\n  open {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "bundles/no-ragrets-47"))
