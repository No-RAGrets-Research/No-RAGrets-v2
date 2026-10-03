import { useMemo, useState } from "react";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { Document, Page, pdfjs } from "react-pdf";
import type { Bundle } from "../bundle";
import { pageScale } from "../geometry";
import { Highlight } from "./Highlight";
// import { AskBox } from "./AskBox"; // TODO(Task 11): uncomment once AskBox exists

// The worker must be configured in this module, not a separate file imported
// from main.tsx: react-pdf's own README warns that module execution order can
// let the default value overwrite a setting made elsewhere (Ruling 10).
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

export function Reader({ bundle }: { bundle: Bundle }) {
  const { paperId = "" } = useParams();
  const [params] = useSearchParams();
  const paper = bundle.papers.find((p) => p.paper_id === decodeURIComponent(paperId));
  const chunks = useMemo(
    () => bundle.chunks.filter((c) => c.paper_id === decodeURIComponent(paperId)),
    [bundle, paperId],
  );
  const focused = chunks.find((c) => c.id === params.get("chunk")) ?? null;
  const firstRegion = focused?.regions[0] ?? null;

  // One page at a time, not a continuous scroll: a 300-page thesis renders in
  // this corpus and rendering every page of it is how a reader locks up.
  const [pageNumber, setPageNumber] = useState(firstRegion?.page ?? 1);
  const [scale, setScale] = useState(1);

  if (!paper) return <p className="p-6">No paper called {decodeURIComponent(paperId)} in this bundle.</p>;

  const pdfMissing = bundle.manifest.missing_pdfs.includes(paper.filename);
  const rects = firstRegion && firstRegion.page === pageNumber ? firstRegion.rects : [];

  return (
    <main className="mx-auto max-w-6xl p-6">
      <Link to="/" className="text-sm text-blue-700 hover:underline">← all papers</Link>
      <h1 className="mt-2 text-xl font-semibold">{paper.paper_id}</h1>

      <div className="mt-4 grid gap-6 md:grid-cols-[2fr_1fr]">
        <div>
          {pdfMissing ? (
            <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
              PDF not in this bundle. The chunk text beside this is what the model sees,
              so citations still resolve — only the page image is missing.
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm">
                <button className="rounded border px-2" onClick={() => setPageNumber((n) => Math.max(1, n - 1))}>
                  prev
                </button>
                <span>page {pageNumber} of {paper.pages}</span>
                <button
                  className="rounded border px-2"
                  onClick={() => setPageNumber((n) => Math.min(paper.pages, n + 1))}
                >
                  next
                </button>
              </div>
              <div className="relative mt-2 inline-block">
                <Document file={`${bundle.baseUrl}/pdfs/${encodeURIComponent(paper.filename)}`}>
                  <Page
                    pageNumber={pageNumber}
                    // Our highlights are our own divs, so neither layer is needed;
                    // turning them off also silences react-pdf's missing-CSS warning.
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                    onLoadSuccess={({ width, originalWidth }) =>
                      setScale(pageScale(width, originalWidth))
                    }
                  />
                </Document>
                <Highlight rects={rects} scale={scale} />
              </div>
            </>
          )}
        </div>

        <aside>
          {focused && (
            <section className="rounded border p-3">
              <h2 className="text-sm font-semibold">Cited passage</h2>
              <p className="mt-1 text-xs text-neutral-500">
                {focused.section ?? "no section"} · page {firstRegion?.page ?? "?"}
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm">{focused.text}</p>
            </section>
          )}
          {/* <AskBox bundle={bundle} scope={{ kind: "paper", paperId: paper.paper_id }} /> */}
        </aside>
      </div>
    </main>
  );
}
