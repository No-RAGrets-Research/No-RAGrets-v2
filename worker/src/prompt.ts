export type AskChunk = { id: string; paper_id: string; section: string | null; text: string };

const SYSTEM = [
  "You answer questions about scientific papers using only the numbered passages provided.",
  "Cite every claim with the bracketed number of the passage it came from, like [2].",
  "If the passages do not contain the answer, say the corpus does not cover it.",
  "Never cite a number that was not provided, and never invent a figure.",
].join(" ");

/** Positional numbering assigned by the sender — the model never names an id,
 *  so a citation cannot point at a chunk that was not sent. */
export function buildMessages(question: string, chunks: AskChunk[]) {
  const passages = chunks
    .map((c, i) => `[${i + 1}] ${c.paper_id} — ${c.section ?? "no section"}\n${c.text}`)
    .join("\n\n");
  return [
    { role: "system", content: SYSTEM },
    { role: "user", content: `Passages:\n\n${passages}\n\nQuestion: ${question}` },
  ];
}

export function citedChunkIds(answer: string, chunks: AskChunk[]): string[] {
  const seen = new Set<string>();
  for (const match of answer.matchAll(/\[(\d+)\]/g)) {
    const index = Number(match[1]) - 1;
    if (index >= 0 && index < chunks.length) seen.add(chunks[index].id);
  }
  return [...seen];
}
