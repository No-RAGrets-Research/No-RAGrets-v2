// Node side of the pdfjs-node runner.
//
// PORTED FROM: No-RAGrets-Master/ui/no-ragrets-ui/src/utils/pdfExtractor.ts
// That file cannot be imported here because it pulls in the UI app's build, so
// this reimplements the same pdf.js text-content call. If the two ever diverge,
// this lab is measuring something the product does not do — keep them in step.
//
// Usage: node lab/pdfjs_runner.mjs <path-to-pdf>   -> one line of JSON on stdout

import { readFileSync } from "node:fs";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const path = process.argv[2];
if (!path) {
  console.error("usage: node lab/pdfjs_runner.mjs <pdf>");
  process.exit(2);
}

const data = new Uint8Array(readFileSync(path));
const pdf = await getDocument({ data, useSystemFonts: true, isEvalSupported: false }).promise;

const pages = [];
for (let number = 1; number <= pdf.numPages; number += 1) {
  const page = await pdf.getPage(number);
  const viewport = page.getViewport({ scale: 1 });
  const content = await page.getTextContent();

  // Group text items into lines by their baseline, then sort left to right.
  const rows = new Map();
  for (const item of content.items) {
    if (!item.str || !item.str.trim()) continue;
    const x = item.transform[4];
    const baseline = item.transform[5];
    const top = viewport.height - baseline - (item.height || 0);
    const key = Math.round(top / 2);
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push({ x, top, width: item.width || 0, height: item.height || 0, str: item.str });
  }

  const lines = [];
  for (const key of [...rows.keys()].sort((a, b) => a - b)) {
    const items = rows.get(key).sort((a, b) => a.x - b.x);
    const text = items.map((i) => i.str).join(" ").replace(/\s+/g, " ").trim();
    if (!text) continue;
    lines.push({
      text,
      bbox: [
        Math.min(...items.map((i) => i.x)),
        Math.min(...items.map((i) => i.top)),
        Math.max(...items.map((i) => i.x + i.width)),
        Math.max(...items.map((i) => i.top + i.height)),
      ],
    });
  }
  pages.push({ page: number, height: viewport.height, lines });
}

process.stdout.write(JSON.stringify({ pages }) + "\n");
