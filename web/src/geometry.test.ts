import { describe, it, expect } from "vitest";
import { pageScale, rectToStyle } from "./geometry";

describe("pageScale", () => {
  it("is the ratio of rendered pixels to PDF points", () => {
    // react-pdf reports width in CSS pixels and originalWidth in points.
    expect(pageScale(1224, 612)).toBe(2);
    expect(pageScale(612, 612)).toBe(1);
  });

  it("falls back to 1 rather than dividing by zero", () => {
    expect(pageScale(800, 0)).toBe(1);
  });
});

describe("rectToStyle", () => {
  it("scales a top-down rect with no flip", () => {
    expect(rectToStyle([10, 20, 90, 50], 2)).toEqual({ left: 20, top: 40, width: 160, height: 60 });
  });

  it("never returns a negative size for an inverted rect", () => {
    const style = rectToStyle([90, 50, 10, 20], 1);
    expect(style.width).toBeGreaterThanOrEqual(0);
    expect(style.height).toBeGreaterThanOrEqual(0);
  });
});
