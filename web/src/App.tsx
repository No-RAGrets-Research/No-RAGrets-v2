import { HashRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { loadBundle, type Bundle } from "./bundle";
import { PaperList } from "./components/PaperList";
import { Reader } from "./components/Reader";

// A hash router, not a browser router: GitHub Pages has no server-side rewrite,
// so /paper/x would 404 on a reload. #/paper/x always resolves to index.html.
const BUNDLE_URL = `${import.meta.env.BASE_URL}bundles/no-ragrets-47`;

// Keyed on paperId so a paper -> paper move remounts the reader. Without it
// the component stays mounted and `pageNumber` and `scale` carry over: paging
// to 15 in a 21-page paper and then opening a 7-page one asks react-pdf for a
// page that does not exist. Only :paperId is in the key, so a `?chunk=`
// citation jump still updates in place as Task 11 verified.
function ReaderRoute({ bundle }: { bundle: Bundle }) {
  const { paperId = "" } = useParams();
  return <Reader key={paperId} bundle={bundle} />;
}

export default function App() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadBundle(BUNDLE_URL).then(setBundle, (e) => setError(String(e)));
  }, []);

  if (error) return <p className="p-6 text-red-700">Could not load the corpus: {error}</p>;
  if (!bundle) return <p className="p-6">Loading the corpus…</p>;

  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<PaperList bundle={bundle} />} />
        <Route path="/paper/:paperId" element={<ReaderRoute bundle={bundle} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
