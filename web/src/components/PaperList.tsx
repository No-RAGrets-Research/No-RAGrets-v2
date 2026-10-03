import { Link } from "react-router-dom";
import type { Bundle } from "../bundle";
// import { SearchPanel } from "./SearchPanel"; // TODO(Task 9): uncomment once SearchPanel exists

export function PaperList({ bundle }: { bundle: Bundle }) {
  const counts = new Map<string, number>();
  for (const chunk of bundle.chunks) {
    counts.set(chunk.paper_id, (counts.get(chunk.paper_id) ?? 0) + 1);
  }
  const missing = new Set(bundle.manifest.missing_pdfs);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="text-2xl font-semibold">{bundle.manifest.name}</h1>
      <p className="mt-1 text-sm text-neutral-600">
        {bundle.manifest.counts.papers} papers, {bundle.manifest.counts.chunks} chunks,
        extracted with {bundle.manifest.source_runner} ({bundle.manifest.runner_version}).
      </p>

      {/* <SearchPanel bundle={bundle} /> */}

      <ul className="mt-6 divide-y">
        {bundle.papers.map((paper) => (
          <li key={paper.paper_id} className="py-2">
            <Link className="text-blue-700 hover:underline" to={`/paper/${encodeURIComponent(paper.paper_id)}`}>
              {paper.paper_id}
            </Link>
            <span className="ml-2 text-sm text-neutral-500">
              {paper.pages} pages · {counts.get(paper.paper_id) ?? 0} chunks
              {missing.has(paper.filename) ? " · PDF not in this bundle" : ""}
            </span>
          </li>
        ))}
      </ul>
    </main>
  );
}
