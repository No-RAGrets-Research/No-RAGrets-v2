export type KvLike = {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
};
export type Limits = { perDay: number; perVisitor: number };
export type Decision = { allowed: true } | { allowed: false; reason: "day-cap" | "visitor-cap" };

const TWO_DAYS = 60 * 60 * 48;

/** Two counters, both scoped to a UTC day, so nothing needs cleaning up.
 *  Not atomic: two simultaneous requests can both read the same count and the
 *  cap can overshoot by one. That is acceptable for a free-tier courtesy limit
 *  and the upgrade path is a Durable Object, which the free plan does not have. */
export async function checkAndCount(
  kv: KvLike, visitor: string, day: string, limits: Limits,
): Promise<Decision> {
  const dayKey = `day:${day}`;
  const visitorKey = `visitor:${day}:${visitor}`;
  const dayCount = Number((await kv.get(dayKey)) ?? 0);
  const visitorCount = Number((await kv.get(visitorKey)) ?? 0);

  if (dayCount >= limits.perDay) return { allowed: false, reason: "day-cap" };
  if (visitorCount >= limits.perVisitor) return { allowed: false, reason: "visitor-cap" };

  await kv.put(dayKey, String(dayCount + 1), { expirationTtl: TWO_DAYS });
  await kv.put(visitorKey, String(visitorCount + 1), { expirationTtl: TWO_DAYS });
  return { allowed: true };
}
