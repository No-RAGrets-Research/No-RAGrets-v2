// vitest/config, not vite: the `test` key below is Vitest's and vite's types reject it.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // GitHub Pages serves this repo at /No-RAGrets-v2/, so asset URLs need the prefix.
  base: "/No-RAGrets-v2/",
  plugins: [react(), tailwindcss()],
  test: { environment: "node" },
});
