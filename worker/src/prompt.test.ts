import { describe, it, expect } from "vitest";
import { buildMessages, citedChunkIds } from "./prompt";

const chunks = [
  { id: "P#1", paper_id: "P", section: "Results", text: "Growth peaked at 30 C." },
  { id: "Q#7", paper_id: "Q", section: "Methods", text: "Cells were grown at 37 C." },
];

describe("buildMessages", () => {
  it("numbers the chunks from 1 and names their paper", () => {
    const messages = buildMessages("What temperature?", chunks);
    const user = messages[messages.length - 1].content;
    expect(user).toContain("[1] P — Results");
    expect(user).toContain("[2] Q — Methods");
    expect(user).toContain("Growth peaked at 30 C.");
    expect(user).toContain("What temperature?");
  });

  it("tells the model to refuse rather than reach", () => {
    const system = buildMessages("q", chunks)[0].content.toLowerCase();
    expect(system).toContain("only");
    expect(system).toContain("does not");
  });
});

describe("citedChunkIds", () => {
  it("maps bracketed numbers back to the ids that were sent", () => {
    expect(citedChunkIds("Growth peaked at 30 C [1], not 37 [2].", chunks))
      .toEqual(["P#1", "Q#7"]);
  });

  it("ignores numbers outside the range and de-duplicates", () => {
    expect(citedChunkIds("see [1] and [1] and [9]", chunks)).toEqual(["P#1"]);
  });

  it("returns nothing when the model cited nothing", () => {
    expect(citedChunkIds("The corpus does not cover this.", chunks)).toEqual([]);
  });
});
