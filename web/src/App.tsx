import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { loadBundle, type Bundle } from "./bundle";
import { PaperList } from "./components/PaperList";
import { Reader } from "./components/Reader";

// A hash router, not a browser router: GitHub Pages has no server-side rewrite,
// so /paper/x would 404 on a reload. #/paper/x always resolves to index.html.
const BUNDLE_URL = `${import.meta.env.BASE_URL}bundles/no-ragrets-47`;

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
        <Route path="/paper/:paperId" element={<Reader bundle={bundle} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
