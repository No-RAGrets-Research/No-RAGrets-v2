/** Reads the layout lab/embed.py writes: float32 scales block, then int8 block. */
export function dequantize(buffer: ArrayBuffer, count: number, dim: number): Float32Array {
  const expected = count * 4 + count * dim;
  if (buffer.byteLength !== expected) {
    throw new Error(`vectors.bin is ${buffer.byteLength} bytes, expected ${expected}`);
  }
  const scales = new Float32Array(buffer, 0, count);
  const quantized = new Int8Array(buffer, count * 4, count * dim);
  const out = new Float32Array(count * dim);
  for (let row = 0; row < count; row++) {
    const factor = scales[row] / 127;
    let sum = 0;
    for (let i = 0; i < dim; i++) {
      const value = quantized[row * dim + i] * factor;
      out[row * dim + i] = value;
      sum += value * value;
    }
    // Re-normalize after dequantizing so cosine stays a plain dot product.
    const norm = Math.sqrt(sum) || 1;
    for (let i = 0; i < dim; i++) out[row * dim + i] /= norm;
  }
  return out;
}
