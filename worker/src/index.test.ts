import { describe, it, expect } from "vitest";
import worker, { type Env } from "./index";

const ORIGIN = "https://no-ragrets-research.github.io";

// Same Map-backed fake KV as caps.test.ts.
function fakeKv() {
  const store = new Map<string, string>();
  return {
    store,
    get: async (key: string) => store.get(key) ?? null,
    put: async (key: string, value: string) => void store.set(key, value),
  };
}

function baseEnv(overrides: Partial<Env> = {}): Env {
  return {
    CAPS: fakeKv(),
    GROQ_API_KEY: "test-key",
    MODEL: "openai/gpt-oss-20b",
    ALLOWED_ORIGIN: ORIGIN,
    PER_DAY: "15",
    PER_VISITOR: "3",
    ...overrides,
  };
}

const VALID_BODY = JSON.stringify({
  question: "What temperature?",
  chunks: [{ id: "P#1", paper_id: "P", section: "Results", text: "Growth peaked at 30 C." }],
});

function postRequest(headers: Record<string, string> = {}) {
  return new Request("https://worker.example/ask", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: VALID_BODY,
  });
}

// None of the paths below reach an LLM call, so none needs a key, a network,
// or a mock of compatChat — if one of these reached it, that would be the bug.
describe("fetch", () => {
  it("answers an OPTIONS preflight with the allow headers and spends no quota", async () => {
    const env = baseEnv();
    const res = await worker.fetch(
      new Request("https://worker.example/ask", { method: "OPTIONS" }),
      env,
    );
    expect(res.status).toBe(204);
    expect(res.headers.get("access-control-allow-origin")).toBe(ORIGIN);
    expect(res.headers.get("access-control-allow-methods")).toContain("POST");
    expect((env.CAPS as ReturnType<typeof fakeKv>).store.size).toBe(0);
  });

  it("rejects a mismatched Origin with 403 and spends no quota", async () => {
    const env = baseEnv();
    const res = await worker.fetch(postRequest({ origin: "https://evil.example" }), env);
    expect(res.status).toBe(403);
    expect((env.CAPS as ReturnType<typeof fakeKv>).store.size).toBe(0);
  });

  it("rejects a missing Origin with 403 and spends no quota", async () => {
    const env = baseEnv();
    const res = await worker.fetch(postRequest(), env);
    expect(res.status).toBe(403);
    expect((env.CAPS as ReturnType<typeof fakeKv>).store.size).toBe(0);
  });

  it("returns 429 with CORS headers once the day cap is reached", async () => {
    const env = baseEnv({ PER_DAY: "0" });
    const res = await worker.fetch(postRequest({ origin: ORIGIN }), env);
    expect(res.status).toBe(429);
    expect(res.headers.get("access-control-allow-origin")).toBe(ORIGIN);
    expect(await res.json()).toEqual({ error: "day-cap" });
  });

  // Pins Finding 2: assertFreeModel throws a plain Error outside any try in
  // the unfixed ordering, so the handler's promise rejects with no Response
  // at all (no CORS headers, no JSON body) rather than failing an assertion
  // below. Against the fix, it resolves to a readable, CORS-bearing error
  // with the cap left untouched.
  it("returns a readable error with CORS headers for a bad MODEL, without spending quota", async () => {
    const env = baseEnv({ MODEL: "gpt-4" });
    const res = await worker.fetch(postRequest({ origin: ORIGIN }), env);
    expect(res.headers.get("access-control-allow-origin")).toBe(ORIGIN);
    const parsed = await res.json();
    expect(parsed).toHaveProperty("error");
    expect((env.CAPS as ReturnType<typeof fakeKv>).store.size).toBe(0);
  });
});
