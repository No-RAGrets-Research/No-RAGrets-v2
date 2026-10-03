import { describe, it, expect } from "vitest";
import { checkAndCount } from "./caps";

function fakeKv() {
  const store = new Map<string, string>();
  return {
    store,
    get: async (key: string) => store.get(key) ?? null,
    put: async (key: string, value: string) => void store.set(key, value),
  };
}

const limits = { perDay: 3, perVisitor: 2 };

describe("checkAndCount", () => {
  it("allows calls under both caps and counts them", async () => {
    const kv = fakeKv();
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits)).toEqual({ allowed: true });
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits)).toEqual({ allowed: true });
  });

  it("stops one visitor at the visitor cap while the day still has room", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits);
    await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits);
    expect(await checkAndCount(kv, "1.2.3.4", "2026-10-01", limits))
      .toEqual({ allowed: false, reason: "visitor-cap" });
    expect(await checkAndCount(kv, "5.6.7.8", "2026-10-01", limits)).toEqual({ allowed: true });
  });

  it("stops everyone at the daily cap", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "a", "2026-10-01", limits);
    await checkAndCount(kv, "b", "2026-10-01", limits);
    await checkAndCount(kv, "c", "2026-10-01", limits);
    expect(await checkAndCount(kv, "d", "2026-10-01", limits))
      .toEqual({ allowed: false, reason: "day-cap" });
  });

  it("starts fresh on a new day", async () => {
    const kv = fakeKv();
    await checkAndCount(kv, "a", "2026-10-01", { perDay: 1, perVisitor: 1 });
    expect(await checkAndCount(kv, "a", "2026-10-02", { perDay: 1, perVisitor: 1 }))
      .toEqual({ allowed: true });
  });
});
