import { useState } from "react";
import { Link } from "react-router-dom";
import type { Bundle } from "../bundle";
import { search } from "../retrieval";
import { askWorker, AskError, answerSegments, type AskReply } from "../ask";

const ASK_URL = import.meta.env.VITE_ASK_URL ?? "";
const TOP_K = 8;

export type Scope = { kind: "paper"; paperId: string } | { kind: "corpus" };

export function AskBox({ bundle, scope }: { bundle: Bundle; scope: Scope }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AskReply | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(bundle.chunks.map((c) => [c.id, c]));

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    setReply(null);
    try {
      const mode = bundle.semantic.available ? "semantic" : "lexical";
      // In paper scope the filter below runs AFTER retrieval, so a corpus-wide
      // top-24 of 2,800 chunks rarely contains enough of one 30-chunk paper to
      // ask about — the reader then sees "nothing matched" for a fair question.
      // Both rankers already score and sort every chunk, so asking for all of
      // them costs nothing and lets the model issue the refusal instead.
      const k = scope.kind === "paper" ? bundle.chunks.length : TOP_K * 3;
      const hits = await search(bundle, question, { mode, k });
      const picked = hits
        .map((h) => byId.get(h.chunk_id)!)
        .filter((c) => scope.kind === "corpus" || c.paper_id === scope.paperId)
        .slice(0, TOP_K);
      if (picked.length === 0) {
        setProblem("Nothing in scope matched that question well enough to ask about.");
      } else {
        setReply(await askWorker(question,
          picked.map(({ id, paper_id, section, text }) => ({ id, paper_id, section, text })),
          { url: ASK_URL }));
      }
    } catch (e) {
      setProblem(
        e instanceof AskError
          ? {
              "not-configured": "Asking is not configured on this deployment. Search still works.",
              offline: "The answer service is unreachable. Search and the papers still work.",
              "day-cap": "The shared daily question limit is used up. Try again tomorrow.",
              "visitor-cap": "You have used your questions for today. Search still works.",
              "rate-limit": "The model is rate-limited right now. Try again in a minute.",
              server: "The answer service failed. Search and the papers still work.",
            }[e.kind]
          : String(e),
      );
    }
    setBusy(false);
  }

  return (
    <section className="mt-4 rounded border p-3">
      <h2 className="text-sm font-semibold">
        Ask {scope.kind === "paper" ? "this paper" : "the corpus"}
      </h2>
      <form onSubmit={ask} className="mt-2 flex gap-2">
        <input
          className="flex-1 rounded border px-2 py-1 text-sm"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What did they measure?"
          aria-label="Ask a question"
          // The Worker rejects anything over 500 with a 400 that ask.ts files
          // under "server", so an over-long question reads as "The answer
          // service failed". The native cap stops it being sent at all.
          maxLength={500}
        />
        <button className="rounded border px-3 text-sm" disabled={busy || !question.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </form>

      {problem && <p className="mt-2 text-sm text-amber-700">{problem}</p>}

      {reply && (
        <div className="mt-3 text-sm">
          <p className="whitespace-pre-wrap">
            {answerSegments(reply.answer, reply.passages).map((segment, i) =>
              segment.kind === "text" ? (
                <span key={i}>{segment.text}</span>
              ) : (
                <Link
                  key={i}
                  className="mx-0.5 rounded bg-blue-50 px-1 text-blue-700 ring-1 ring-blue-200"
                  to={`/paper/${encodeURIComponent(byId.get(segment.chunk_id)!.paper_id)}?chunk=${encodeURIComponent(segment.chunk_id)}`}
                >
                  [{segment.label}]
                </Link>
              ),
            )}
          </p>
          <p className="mt-2 text-xs text-neutral-500">
            {reply.inTokens} in / {reply.outTokens} out · {reply.ms} ms · answered only from the
            passages cited above
          </p>
        </div>
      )}
    </section>
  );
}
