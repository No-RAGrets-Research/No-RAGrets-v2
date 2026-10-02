"""Embed chunk text offline and write int8 vectors for the reader.

Kept out of export.py because this is the only step with a heavy dependency
and the only one `--no-embed` skips.

The model must match what the browser loads (Xenova/bge-small-en-v1.5), or
cosine scores compare two different vector spaces and look fine while being
meaningless. `manifest.json` records the model so the reader can refuse.
"""
import json
import pathlib

import numpy as np

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384


def embed_texts(texts, embedder=None):
    """float32 (n, DIM) with L2-normalized rows."""
    if embedder is None:
        from fastembed import TextEmbedding

        model = TextEmbedding(MODEL)
        embedder = lambda batch: list(model.embed(batch))      # noqa: E731
    raw = np.asarray(list(embedder(list(texts))), dtype=np.float32)
    if raw.ndim != 2 or raw.shape[1] != DIM:
        raise ValueError(f"expected (n, {DIM}) embeddings, got {raw.shape}")
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    # Normalize explicitly rather than trusting the embedder to have done it:
    # cosine is only a dot product on unit rows, and this is idempotent.
    return raw / norms


def quantize(vectors):
    """int8 values plus one float32 scale per row (symmetric max-abs)."""
    scales = np.abs(vectors).max(axis=1)
    scales[scales == 0] = 1.0
    q = np.round(vectors / scales[:, None] * 127.0).astype(np.int8)
    return q, scales.astype(np.float32)


def dequantize(q, scales):
    return q.astype(np.float32) * (np.asarray(scales, dtype=np.float32)[:, None] / 127.0)


def quantization_error(vectors, q, scales):
    """(mean 1 - cosine, worst cosine) between the originals and the round-trip."""
    back = dequantize(q, scales)
    back /= np.linalg.norm(back, axis=1, keepdims=True)
    cos = (vectors * back).sum(axis=1)
    return float(np.mean(1.0 - cos)), float(np.min(cos))


def write_vectors(out_dir, texts, embedder=None):
    """Write vectors.bin and record the model, dim and hash in manifest.json."""
    import hashlib

    out_dir = pathlib.Path(out_dir)
    vectors = embed_texts(texts, embedder=embedder)
    q, scales = quantize(vectors)
    mean_error, worst_cos = quantization_error(vectors, q, scales)

    payload = scales.tobytes() + q.tobytes()
    (out_dir / "vectors.bin").write_bytes(payload)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["embed_model"] = MODEL
    manifest["dim"] = DIM
    manifest.setdefault("files", {})["vectors.bin"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {"count": len(vectors), "dim": DIM, "bytes": len(payload),
            "mean_cosine_error": mean_error, "worst_cosine": worst_cos}
