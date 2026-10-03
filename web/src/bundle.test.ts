import { describe, it, expect } from "vitest";
import { loadBundle, QUERY_MODEL } from "./bundle";

function fakeFetch(files: Record<string, unknown | ArrayBuffer>) {
  return async (url: string) => {
    const name = url.split("/").pop()!;
    if (!(name in files)) return new Response(null, { status: 404 });
    const value = files[name];
    if (value instanceof ArrayBuffer) return new Response(value, { status: 200 });
    return new Response(JSON.stringify(value), { status: 200 });
  };
}

const manifest = {
  corpus_id: "fix", name: "Fixture", built_at: "2026-10-01T00:00:00+00:00",
  source_runner: "docling-default", runner_version: "test",
  embed_model: "BAAI/bge-small-en-v1.5", dim: 4,
  counts: { papers: 1, chunks: 2 }, files: {}, missing_pdfs: [],
};
const papers = [{ paper_id: "P", filename: "P.pdf", pages: 2, sha256: "0".repeat(64) }];
const chunks = [
  { id: "P#0", paper_id: "P", section: "Results", text: "methane yield rose", chars: 18,
    regions: [{ page: 1, rects: [[10, 20, 90, 40]] }] },
  { id: "P#1", paper_id: "P", section: "Results", text: "no geometry here", chars: 16, regions: [] },
];

function vectorsBin(): ArrayBuffer {
  // 2 rows x dim 4: scales block (float32) then int8 block, per lab/embed.py
  const buffer = new ArrayBuffer(2 * 4 + 2 * 4);
  new Float32Array(buffer, 0, 2).set([1, 1]);
  new Int8Array(buffer, 8, 8).set([127, 0, 0, 0, 0, 127, 0, 0]);
  return buffer;
}

describe("loadBundle", () => {
  it("loads papers, chunks and vectors and reports semantic as available", async () => {
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": manifest, "papers.json": papers,
                         "chunks.json": chunks, "vectors.bin": vectorsBin() }),
    });
    expect(bundle.papers).toHaveLength(1);
    expect(bundle.chunks[0].regions[0].page).toBe(1);
    expect(bundle.semantic).toEqual({ available: true, model: QUERY_MODEL });
    expect(bundle.vectors).toHaveLength(2 * 4);
  });

  it("refuses semantic search when the manifest model is not the one the app loads", async () => {
    const wrong = { ...manifest, embed_model: "intfloat/e5-base-v2" };
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": wrong, "papers.json": papers,
                         "chunks.json": chunks, "vectors.bin": vectorsBin() }),
    });
    expect(bundle.semantic).toEqual({ available: false, reason: "embed-model-mismatch" });
    expect(bundle.vectors).toBeNull();
    expect(bundle.chunks).toHaveLength(2);   // reading and lexical search survive
  });

  it("falls back to lexical when vectors.bin is absent", async () => {
    const bundle = await loadBundle("/bundles/fix", {
      fetch: fakeFetch({ "manifest.json": { ...manifest, embed_model: null, dim: null },
                         "papers.json": papers, "chunks.json": chunks }),
    });
    expect(bundle.semantic).toEqual({ available: false, reason: "no-vectors" });
  });

  it("throws when the bundle itself cannot be read", async () => {
    await expect(loadBundle("/bundles/fix", { fetch: fakeFetch({}) })).rejects.toThrow(/manifest/);
  });
});
