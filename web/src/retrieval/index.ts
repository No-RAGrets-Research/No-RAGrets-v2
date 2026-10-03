import type { Bundle } from "../bundle";
import { buildIndex, rank, type Bm25Index } from "./bm25";
import { cosineTopK } from "./vectors";
import { embedQuery } from "./embedder";

export type Mode = "semantic" | "lexical";
export type Hit = { chunk_id: string; score: number; mode: Mode };

const indexes = new WeakMap<Bundle, Bm25Index>();

function lexicalIndex(bundle: Bundle): Bm25Index {
  let index = indexes.get(bundle);
  if (!index) {
    index = buildIndex(bundle.chunks);
    indexes.set(bundle, index);
  }
  return index;
}

/** One mode per call. There is deliberately no blended mode: a merged score
 *  would be the composite number this project refuses to ship. */
export async function search(
  bundle: Bundle, query: string, { mode, k = 10 }: { mode: Mode; k?: number },
): Promise<Hit[]> {
  if (!query.trim()) return [];

  if (mode === "lexical") {
    return rank(lexicalIndex(bundle), query, k).map((hit) => ({ ...hit, mode }));
  }

  if (!bundle.semantic.available || !bundle.vectors || !bundle.manifest.dim) {
    throw new Error(`semantic search unavailable: ${
      bundle.semantic.available ? "no vectors" : bundle.semantic.reason}`);
  }
  const query_vector = await embedQuery(query);
  const hits = cosineTopK(
    query_vector, bundle.vectors, bundle.manifest.counts.chunks, bundle.manifest.dim, k,
  );
  return hits.map(({ index, score }) => ({ chunk_id: bundle.chunks[index].id, score, mode }));
}
