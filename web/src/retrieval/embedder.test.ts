import { describe, it, expect, vi, beforeEach } from "vitest";

const { pipelineMock } = vi.hoisted(() => ({ pipelineMock: vi.fn() }));

vi.mock("@huggingface/transformers", () => ({ pipeline: pipelineMock }));

import { embedQuery } from "./embedder";

describe("embedQuery", () => {
  beforeEach(() => {
    pipelineMock.mockReset();
  });

  it("retries the model load on the next call instead of staying poisoned", async () => {
    pipelineMock
      .mockRejectedValueOnce(new Error("cdn hiccup"))
      .mockResolvedValueOnce(async () => ({ data: new Float32Array([1, 0]) }));

    await expect(embedQuery("hello")).rejects.toThrow("cdn hiccup");
    await expect(embedQuery("hello")).resolves.toEqual(new Float32Array([1, 0]));
    expect(pipelineMock).toHaveBeenCalledTimes(2);
  });
});
