import type { Rect } from "./bundle";

/** Rendered CSS pixels per PDF point.
 *
 * Derived from what react-pdf reports rather than assumed from a scale prop or
 * a 72-vs-96 dpi guess: `width` is the rendered size, `originalWidth` is points.
 * v1 hardcoded scales in two places and they disagreed.
 */
export function pageScale(renderedWidth: number, originalWidthInPoints: number): number {
  if (!originalWidthInPoints) return 1;
  return renderedWidth / originalWidthInPoints;
}

/** A top-down [x0, top, x1, bottom] rect in points to CSS pixel offsets.
 *
 * No coordinate flip: lab/runners.py already converted docling's bottom-left
 * origin once, offline. If highlights ever come out mirrored, fix it there.
 */
export function rectToStyle([x0, top, x1, bottom]: Rect, scale: number) {
  return {
    left: Math.min(x0, x1) * scale,
    top: Math.min(top, bottom) * scale,
    width: Math.abs(x1 - x0) * scale,
    height: Math.abs(bottom - top) * scale,
  };
}
