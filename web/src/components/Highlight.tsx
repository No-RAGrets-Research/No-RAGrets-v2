import type { Rect } from "../bundle";
import { rectToStyle } from "../geometry";

/** Absolutely-positioned divs over a rendered page. Divs rather than a canvas:
 *  they take CSS transitions, survive a re-render, and need no redraw loop. */
export function Highlight({ rects, scale }: { rects: Rect[]; scale: number }) {
  return (
    <>
      {rects.map((rect, i) => (
        <div
          key={i}
          aria-hidden
          className="absolute bg-yellow-300/40 ring-2 ring-yellow-500 rounded-sm"
          style={rectToStyle(rect, scale)}
        />
      ))}
    </>
  );
}
