export type AskChunk = { id: string; paper_id: string; section: string | null; text: string };
export type AskReply = {
  answer: string;
  /** Positional: passages[n-1] is the chunk the answer labels [n]. */
  passages: string[];
  /** The subset the model actually referenced. Display only. */
  cited: string[];
  inTokens: number; outTokens: number; ms: number;
};
export type AskErrorKind =
  | "not-configured" | "offline" | "day-cap" | "visitor-cap" | "rate-limit" | "server";

export class AskError extends Error {
  // Not a constructor parameter property: this tsconfig sets
  // erasableSyntaxOnly, which forbids that shorthand because it emits a
  // runtime assignment, not just erasable type syntax.
  readonly kind: AskErrorKind;
  constructor(kind: AskErrorKind, message: string) {
    super(message);
    this.kind = kind;
  }
}

export async function askWorker(
  question: string, chunks: AskChunk[],
  { url, fetch: fetchImpl = fetch }: { url: string; fetch?: typeof fetch },
): Promise<AskReply> {
  if (!url) throw new AskError("not-configured", "No ask endpoint is configured.");

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, chunks }),
    });
  } catch (e) {
    // A thrown fetch is the network, not the server: different message for the reader.
    throw new AskError("offline", `Could not reach the answer service: ${String(e)}`);
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    const error = body.error ?? String(response.status);
    const kind: AskErrorKind =
      error === "day-cap" || error === "visitor-cap" || error === "rate-limit" ? error : "server";
    throw new AskError(kind, error);
  }
  return (await response.json()) as AskReply;
}

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "citation"; label: number; chunk_id: string };

/** Turns `[n]` markers into citation segments, in order.
 *
 * `passages` is positional — the ids in the order they were sent — so label n
 * maps to passages[n-1]. A number with no matching entry stays plain text
 * rather than becoming a link to nothing. */
export function answerSegments(answer: string, passages: string[]): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(/\[(\d+)\]/g)) {
    const at = match.index ?? 0;
    if (at > cursor) segments.push({ kind: "text", text: answer.slice(cursor, at) });
    const label = Number(match[1]);
    const chunk_id = passages[label - 1];
    segments.push(chunk_id ? { kind: "citation", label, chunk_id } : { kind: "text", text: match[0] });
    cursor = at + match[0].length;
  }
  if (cursor < answer.length) segments.push({ kind: "text", text: answer.slice(cursor) });
  return segments;
}
