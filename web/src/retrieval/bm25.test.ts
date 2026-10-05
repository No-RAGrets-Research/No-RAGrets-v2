import { describe, it, expect } from "vitest";
import { buildIndex, rank } from "./bm25";
import type { Chunk } from "../bundle";

const chunk = (id: string, text: string): Chunk =>
  ({ id, paper_id: "P", section: null, text, chars: text.length, regions: [] });

const chunks = [
  chunk("a", "methane oxidation by methanotrophs in a bioreactor"),
  chunk("b", "the bioreactor was stirred at 300 rpm"),
  chunk("c", "nitrogen fixation in soil samples"),
];

describe("bm25", () => {
  it("ranks the chunk that repeats the query term first", () => {
    const hits = rank(buildIndex(chunks), "methane methanotrophs", 3);
    expect(hits[0].chunk_id).toBe("a");
    expect(hits[0].score).toBeGreaterThan(0);
  });

  it("weighs a term that appears in every document far below a rare one", () => {
    // BM25's smoothed idf, log(1 + (N - df + 0.5)/(df + 0.5)), is 0.182 for a
    // term in every document — small, not zero. The property worth pinning is
    // the ordering, not an absolute floor.
    const index = buildIndex(chunks);
    const common = rank(index, "bioreactor", 3)[0].score;     // in 2 of 3 chunks
    const rare = rank(index, "methanotrophs", 3)[0].score;    // in 1 of 3
    expect(rare).toBeGreaterThan(common * 2);
  });

  it("returns nothing for an empty or unmatched query", () => {
    const index = buildIndex(chunks);
    expect(rank(index, "   ", 5)).toEqual([]);
    expect(rank(index, "zebra", 5)).toEqual([]);
  });

  it("respects k", () => {
    expect(rank(buildIndex(chunks), "bioreactor", 1)).toHaveLength(1);
  });
});
