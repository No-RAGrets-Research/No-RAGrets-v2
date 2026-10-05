import type { Chunk } from "../bundle";

const K1 = 1.2;
const B = 0.75;

export type Bm25Index = {
  ids: string[];
  lengths: number[];
  avgLength: number;
  /** term -> [docIndex, termFrequency][] */
  postings: Map<string, [number, number][]>;
};

export function tokenize(text: string): string[] {
  return text.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 1);
}

export function buildIndex(chunks: Chunk[]): Bm25Index {
  const ids: string[] = [];
  const lengths: number[] = [];
  const postings = new Map<string, [number, number][]>();

  chunks.forEach((chunk, doc) => {
    const tokens = tokenize(chunk.text);
    ids.push(chunk.id);
    lengths.push(tokens.length);
    const counts = new Map<string, number>();
    for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
    for (const [token, frequency] of counts) {
      const list = postings.get(token) ?? [];
      list.push([doc, frequency]);
      postings.set(token, list);
    }
  });

  const total = lengths.reduce((a, b) => a + b, 0);
  return { ids, lengths, avgLength: total / (lengths.length || 1), postings };
}

export function rank(index: Bm25Index, query: string, k: number) {
  const terms = tokenize(query);
  if (terms.length === 0) return [];
  const docCount = index.ids.length;
  const scores = new Map<number, number>();

  for (const term of terms) {
    const postings = index.postings.get(term);
    if (!postings) continue;
    // Robertson/Sparck-Jones idf, smoothed: never negative, and a term appearing
    // in every document still scores a small positive value rather than zero.
    // The test pins the ordering — a rare term must outscore a common one — not
    // an absolute floor.
    const idf = Math.log(1 + (docCount - postings.length + 0.5) / (postings.length + 0.5));
    for (const [doc, frequency] of postings) {
      const norm = frequency + K1 * (1 - B + (B * index.lengths[doc]) / index.avgLength);
      scores.set(doc, (scores.get(doc) ?? 0) + (idf * frequency * (K1 + 1)) / norm);
    }
  }

  return [...scores.entries()]
    .filter(([, score]) => score > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([doc, score]) => ({ chunk_id: index.ids[doc], score }));
}
