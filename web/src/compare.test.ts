import { describe, it, expect } from "vitest";
import { compareRankings } from "./compare";
import type { Hit } from "./retrieval";

const hit = (id: string, score: number, mode: Hit["mode"]): Hit =>
  ({ chunk_id: id, score, mode });

describe("compareRankings", () => {
  it("reports overlap and each mode's exclusives without merging scores", () => {
    const semantic = [hit("a", 0.9, "semantic"), hit("b", 0.8, "semantic")];
    const lexical = [hit("b", 4.1, "lexical"), hit("c", 2.0, "lexical")];
    expect(compareRankings(semantic, lexical)).toEqual({
      overlap: 1, onlySemantic: ["a"], onlyLexical: ["c"],
    });
  });

  it("handles one side being empty", () => {
    expect(compareRankings([], [hit("a", 1, "lexical")])).toEqual({
      overlap: 0, onlySemantic: [], onlyLexical: ["a"],
    });
  });
});
