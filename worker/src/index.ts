import { compatChat, GROQ } from "llm-kit/openai-compat";
import { LlmError, assertFreeModel } from "llm-kit";
import { buildMessages, citedChunkIds, type AskChunk } from "./prompt";
import { checkAndCount, type KvLike } from "./caps";

export type Env = {
  CAPS: KvLike; GROQ_API_KEY: string; MODEL: string;
  ALLOWED_ORIGIN: string; PER_DAY: string; PER_VISITOR: string;
};

const MAX_CHUNKS = 12;
const MAX_QUESTION = 500;

function json(body: unknown, status: number, origin: string) {
  // A 204 may not carry a body per the Fetch spec; the Response constructor
  // throws if given one. The OPTIONS preflight is the only 204 this sends.
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": origin,
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "POST, OPTIONS",
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const origin = env.ALLOWED_ORIGIN;
    // The preflight carries no body and spends no quota, so it is answered
    // before the origin gate below rather than being subject to it.
    if (request.method === "OPTIONS") return json({}, 204, origin);

    // CORS headers only stop a browser from *reading* a cross-origin response;
    // they enforce nothing against a direct caller (curl, another server).
    // Check the real request's Origin ourselves, before any cap check or LLM
    // call, so a non-browser caller can't spend quota either.
    if (request.headers.get("origin") !== origin) {
      return json({ error: "forbidden origin" }, 403, origin);
    }

    if (request.method !== "POST") return json({ error: "POST only" }, 405, origin);
    if (new URL(request.url).pathname !== "/ask") return json({ error: "not found" }, 404, origin);

    let body: { question?: string; chunks?: AskChunk[] };
    try {
      body = await request.json();
    } catch {
      return json({ error: "body must be JSON" }, 400, origin);
    }
    const question = (body.question ?? "").trim();
    const chunks = (body.chunks ?? []).slice(0, MAX_CHUNKS);
    if (!question || question.length > MAX_QUESTION) {
      return json({ error: `question must be 1-${MAX_QUESTION} characters` }, 400, origin);
    }
    if (chunks.length === 0) return json({ error: "no passages supplied" }, 400, origin);

    // Checked before the cap is touched, and in its own try: assertFreeModel
    // throws a plain Error (not LlmError), and a misconfigured model must not
    // cost a visitor's or the day's quota on a request that answers nothing.
    try {
      assertFreeModel(env.MODEL);
    } catch {
      console.log("ask failed kind=bad-model");    // counts and kinds only, never the question
      return json({ error: "bad-model" }, 500, origin);
    }

    // Same reasoning, and the same place in the order: an unset secret is a
    // deploy mistake, not a visitor's fault. llm-kit only raises no-key for an
    // empty string, so an absent binding would instead reach Groq as a missing
    // Authorization header, come back 401, and charge a visitor and the day
    // for an answer nobody got.
    if (!env.GROQ_API_KEY) {
      console.log("ask failed kind=no-key");
      return json({ error: "no-key" }, 500, origin);
    }

    const visitor = request.headers.get("cf-connecting-ip") ?? "unknown";
    const day = new Date().toISOString().slice(0, 10);
    const decision = await checkAndCount(env.CAPS, visitor, day, {
      perDay: Number(env.PER_DAY), perVisitor: Number(env.PER_VISITOR),
    });
    if (!decision.allowed) return json({ error: decision.reason }, 429, origin);

    try {
      const reply = await compatChat(buildMessages(question, chunks), {
        baseUrl: GROQ, model: env.MODEL, apiKey: env.GROQ_API_KEY,
        temperature: 0, timeoutMs: 30_000,
      });
      return json({
        answer: reply.content,
        // Positional: passages[n - 1] is the chunk labelled [n] in the answer.
        // `cited` is the subset the model actually referenced, for display only.
        passages: chunks.map((c) => c.id),
        cited: citedChunkIds(reply.content, chunks),
        inTokens: reply.inTokens, outTokens: reply.outTokens, ms: reply.ms,
      }, 200, origin);
    } catch (e) {
      // llm-kit's typed kinds let the UI say which thing broke instead of
      // string-matching an error body.
      const kind = e instanceof LlmError ? e.kind : "unknown";
      const status = kind === "rate-limit" ? 429 : kind === "auth" || kind === "no-key" ? 500 : 502;
      console.log(`ask failed kind=${kind}`);      // counts and kinds only, never the question
      return json({ error: kind }, status, origin);
    }
  },
};
