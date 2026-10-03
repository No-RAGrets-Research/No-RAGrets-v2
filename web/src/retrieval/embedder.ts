import { QUERY_MODEL } from "../bundle";

let pending: Promise<unknown> | null = null;

/** Embeds one query, loading the model on first use (about 33MB, then cached).
 *
 * `pooling: "cls"` is NOT the library default — it is what bge models use, and
 * what fastembed does on the Python side. Mean pooling here would produce
 * vectors in a different space from the bundle's while the model id still
 * matched, so no guard would catch it. The parity test is what pins this.
 */
export async function embedQuery(text: string): Promise<Float32Array> {
  if (!pending) {
    pending = import("@huggingface/transformers").then(({ pipeline }) =>
      pipeline("feature-extraction", QUERY_MODEL, { dtype: "q8" }),
    );
  }
  const extractor = (await pending) as (
    input: string, options: { pooling: "cls"; normalize: boolean },
  ) => Promise<{ data: Float32Array }>;
  const output = await extractor(text, { pooling: "cls", normalize: true });
  return new Float32Array(output.data);
}
