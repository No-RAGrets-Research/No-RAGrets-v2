/** The bundle contract. Written by `python -m lab export`; read only here. */

export type Rect = [number, number, number, number];   // x0, top, x1, bottom, PDF points, top-down
export type Region = { page: number; rects: Rect[] };
export type Chunk = {
  id: string; paper_id: string; section: string | null;
  text: string; chars: number; regions: Region[];
};
export type Paper = { paper_id: string; filename: string; pages: number; sha256: string };
export type Manifest = {
  corpus_id: string; name: string; built_at: string;
  source_runner: string; runner_version: string;
  embed_model: string | null; dim: number | null;
  counts: { papers: number; chunks: number };
  files: Record<string, string>; missing_pdfs: string[];
};
export type SemanticStatus =
  | { available: true; model: string }
  | { available: false; reason: "no-vectors" | "embed-model-mismatch" };
export type Bundle = {
  baseUrl: string; manifest: Manifest; papers: Paper[]; chunks: Chunk[];
  /** Dequantized, L2-normalized, row-major count x dim. Null when unavailable. */
  vectors: Float32Array | null;
  semantic: SemanticStatus;
};

/** The browser-side half of the pair in lab/embed.py. Same weights. */
export const QUERY_MODEL = "Xenova/bge-small-en-v1.5";
export const MODEL_PAIRS: Record<string, string> = {
  "BAAI/bge-small-en-v1.5": QUERY_MODEL,
};

export async function loadBundle(
  baseUrl: string,
  opts: { fetch?: typeof fetch } = {},
): Promise<Bundle> {
  const get = opts.fetch ?? fetch;

  const read = async (name: string) => {
    const response = await get(`${baseUrl}/${name}`);
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    return response;
  };

  const manifest = (await (await read("manifest.json")).json()) as Manifest;
  const papers = (await (await read("papers.json")).json()) as Paper[];
  const chunks = (await (await read("chunks.json")).json()) as Chunk[];

  // A mismatch here produces cosine scores across two different vector spaces:
  // plausible-looking numbers that mean nothing. Refuse instead of warning.
  if (!manifest.embed_model) {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "no-vectors" } };
  }
  if (MODEL_PAIRS[manifest.embed_model] !== QUERY_MODEL) {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "embed-model-mismatch" } };
  }

  const dim = manifest.dim ?? 0;
  const count = manifest.counts.chunks;
  let vectors: Float32Array | null = null;
  try {
    const buffer = await (await read("vectors.bin")).arrayBuffer();
    const { dequantize } = await import("./retrieval/vectors");
    vectors = dequantize(buffer, count, dim);
  } catch {
    return { baseUrl, manifest, papers, chunks, vectors: null,
             semantic: { available: false, reason: "no-vectors" } };
  }
  return { baseUrl, manifest, papers, chunks, vectors,
           semantic: { available: true, model: QUERY_MODEL } };
}
