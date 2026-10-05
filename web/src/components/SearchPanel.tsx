import { useState } from "react";
import { Link } from "react-router-dom";
import type { Bundle, Chunk } from "../bundle";
import { search, type Hit } from "../retrieval";
import { compareRankings } from "../compare";

function Results({ title, hits, byId, note }: {
  title: string; hits: Hit[]; byId: Map<string, Chunk>; note?: string;
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {note && <p className="text-xs text-amber-700">{note}</p>}
      <ol className="mt-1 space-y-2">
        {hits.map((hit) => {
          const chunk = byId.get(hit.chunk_id)!;
          const page = chunk.regions[0]?.page;
          return (
            <li key={hit.chunk_id} className="text-sm">
              <Link
                className="text-blue-700 hover:underline"
                to={`/paper/${encodeURIComponent(chunk.paper_id)}?chunk=${encodeURIComponent(chunk.id)}`}
              >
                {chunk.paper_id}
              </Link>
              <span className="ml-1 text-xs text-neutral-500">
                {chunk.section ?? "no section"}
                {page ? ` · p${page}` : " · no page geometry"} · {hit.score.toFixed(3)}
              </span>
              <p className="text-neutral-700">{chunk.text.slice(0, 180)}…</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function SearchPanel({ bundle }: { bundle: Bundle }) {
  const [query, setQuery] = useState("");
  const [semantic, setSemantic] = useState<Hit[]>([]);
  const [lexical, setLexical] = useState<Hit[]>([]);
  const [semanticNote, setSemanticNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Distinguishes "searched and found nothing" from "has not searched yet".
  // Without it a zero-hit query removes the whole results region and reads
  // as a broken search box rather than an empty result (Ruling 22).
  const [searched, setSearched] = useState(false);
  const byId = new Map(bundle.chunks.map((c) => [c.id, c]));

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSemanticNote(null);
    // Lexical first and separately: it is instant, so results are on screen
    // while the 33MB embedding model is still arriving on a first visit.
    setLexical(await search(bundle, query, { mode: "lexical", k: 10 }));
    try {
      setSemantic(await search(bundle, query, { mode: "semantic", k: 10 }));
    } catch (e) {
      setSemantic([]);
      setSemanticNote(
        bundle.semantic.available
          ? `Semantic search failed: ${String(e)}`
          : bundle.semantic.reason === "embed-model-mismatch"
            ? "Semantic search is off: this bundle was built with a different embedding model."
            : "Semantic search is off: this bundle has no vectors.",
      );
    }
    setSearched(true);
    setBusy(false);
  }

  const diff = compareRankings(semantic, lexical);

  return (
    <section className="mt-6">
      <form onSubmit={run} className="flex gap-2">
        <input
          className="flex-1 rounded border px-2 py-1"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the corpus"
          aria-label="Search the corpus"
        />
        <button className="rounded border px-3" disabled={busy}>{busy ? "…" : "Search"}</button>
      </form>

      {searched && semantic.length === 0 && lexical.length === 0 && (
        <p className="mt-3 text-sm text-neutral-700">
          No results for “{query}”.{semanticNote ? ` ${semanticNote}` : ""}
        </p>
      )}

      {(semantic.length > 0 || lexical.length > 0) && (
        <>
          {semantic.length > 0 && lexical.length > 0 && (
            <p className="mt-3 text-xs text-neutral-600">
              {diff.overlap} of {Math.min(semantic.length, lexical.length)} results appear in both
              rankings. The two are never combined into one score — read them as two opinions.
            </p>
          )}
          <div className="mt-2 grid gap-6 md:grid-cols-2">
            <Results title="Semantic" hits={semantic} byId={byId} note={semanticNote ?? undefined} />
            <Results title="Lexical (BM25)" hits={lexical} byId={byId} />
          </div>
        </>
      )}
    </section>
  );
}
