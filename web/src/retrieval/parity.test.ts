import { describe, it, expect } from "vitest";
import parity from "../../test-fixtures/parity.json";
import { embedQuery } from "./embedder";

// Downloads the ONNX model on first run (about 33MB, then cached on disk).
// SKIP_PARITY=1 skips it; do not skip it after touching the embedder.
const run = process.env.SKIP_PARITY ? it.skip : it;

describe("python/browser embedding parity", () => {
  run("agrees with fastembed on the same sentences", async () => {
    for (let i = 0; i < parity.texts.length; i++) {
      const mine = await embedQuery(parity.texts[i]);
      const theirs = parity.vectors[i] as number[];
      expect(mine).toHaveLength(theirs.length);
      let dot = 0;
      for (let j = 0; j < theirs.length; j++) dot += mine[j] * theirs[j];
      // Same weights, same pooling, both normalized: cosine should be ~1.
      // Below 0.99 means the pooling or the model pair is wrong.
      expect(dot).toBeGreaterThan(0.99);
    }
  }, 180_000);
});
