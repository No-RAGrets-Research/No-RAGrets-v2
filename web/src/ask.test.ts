import { describe, it, expect } from "vitest";
import { askWorker, answerSegments } from "./ask";

const chunks = [{ id: "P#1", paper_id: "P", section: "Results", text: "Growth peaked at 30 C." }];
const url = "https://worker.example/ask";

describe("askWorker", () => {
  it("returns the answer and citations on success", async () => {
    const fetchImpl = async () =>
      new Response(JSON.stringify({ answer: "30 C [1].", passages: ["P#1"], cited: ["P#1"],
                                    inTokens: 10, outTokens: 4, ms: 500 }), { status: 200 });
    const reply = await askWorker("q", chunks, { url, fetch: fetchImpl });
    expect(reply.answer).toBe("30 C [1].");
    expect(reply.passages).toEqual(["P#1"]);
  });

  it("maps each cap and failure to a distinct kind", async () => {
    const cases: [number, string, string][] = [
      [429, "day-cap", "day-cap"],
      [429, "visitor-cap", "visitor-cap"],
      [429, "rate-limit", "rate-limit"],
      [502, "unreachable", "server"],
      [500, "no-key", "server"],
      // Real Worker (worker/src/index.ts): an Origin mismatch is checked before
      // any cap or LLM call and returns 403 "forbidden origin". Not in the
      // brief's table; added because it's a case the handler actually emits
      // and the generic "server" bucket (keyed on body, not status) covers it.
      [403, "forbidden origin", "server"],
    ];
    for (const [status, body, kind] of cases) {
      const fetchImpl = async () => new Response(JSON.stringify({ error: body }), { status });
      await expect(askWorker("q", chunks, { url, fetch: fetchImpl }))
        .rejects.toMatchObject({ kind });
    }
  });

  it("reports a network failure as offline rather than a server error", async () => {
    const fetchImpl = async () => { throw new TypeError("Failed to fetch"); };
    await expect(askWorker("q", chunks, { url, fetch: fetchImpl })).rejects.toMatchObject({ kind: "offline" });
  });

  it("refuses to call an unconfigured worker", async () => {
    await expect(askWorker("q", chunks, { url: "", fetch: async () => new Response("{}") }))
      .rejects.toMatchObject({ kind: "not-configured" });
  });
});

describe("answerSegments", () => {
  it("splits an answer into text and citation segments in order, by position", () => {
    // Deliberately cited out of order below: label 2 must still resolve to the
    // SECOND passage sent, not to the second one the model happened to mention.
    expect(answerSegments("Peaked at 30 C [1] not 37 [2].", ["P#1", "Q#7"])).toEqual([
      { kind: "text", text: "Peaked at 30 C " },
      { kind: "citation", label: 1, chunk_id: "P#1" },
      { kind: "text", text: " not 37 " },
      { kind: "citation", label: 2, chunk_id: "Q#7" },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves a citation number with no matching id as plain text", () => {
    expect(answerSegments("see [3]", ["P#1"])).toEqual([
      { kind: "text", text: "see " },
      { kind: "text", text: "[3]" },
    ]);
  });
});
