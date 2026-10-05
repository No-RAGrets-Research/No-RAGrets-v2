import type { Hit } from "./retrieval";

/** How the two rankings differ, as counts and ids — never as a merged score.
 *  This is the number that answers "do the embeddings earn their 1.1MB". */
export function compareRankings(semantic: Hit[], lexical: Hit[]) {
  const semanticIds = semantic.map((h) => h.chunk_id);
  const lexicalIds = lexical.map((h) => h.chunk_id);
  const lexicalSet = new Set(lexicalIds);
  const semanticSet = new Set(semanticIds);
  return {
    overlap: semanticIds.filter((id) => lexicalSet.has(id)).length,
    onlySemantic: semanticIds.filter((id) => !lexicalSet.has(id)),
    onlyLexical: lexicalIds.filter((id) => !semanticSet.has(id)),
  };
}
