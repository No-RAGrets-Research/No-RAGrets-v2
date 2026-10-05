import { describe, it, expect } from "vitest";
import { cosineTopK, dequantize } from "./vectors";

describe("cosineTopK", () => {
  it("ranks the identical row first and the opposite row last", () => {
    const dim = 2;
    const matrix = new Float32Array([1, 0, 0.7071, 0.7071, -1, 0]);
    const hits = cosineTopK(new Float32Array([1, 0]), matrix, 3, dim, 3);
    expect(hits.map((h) => h.index)).toEqual([0, 1, 2]);
    expect(hits[0].score).toBeCloseTo(1, 5);
    expect(hits[2].score).toBeCloseTo(-1, 5);
  });

  it("respects k", () => {
    const matrix = new Float32Array([1, 0, 0, 1]);
    expect(cosineTopK(new Float32Array([1, 0]), matrix, 2, 2, 1)).toHaveLength(1);
  });
});

describe("dequantize", () => {
  it("rejects a file whose length disagrees with the manifest", () => {
    expect(() => dequantize(new ArrayBuffer(10), 2, 4)).toThrow(/expected/);
  });
});
