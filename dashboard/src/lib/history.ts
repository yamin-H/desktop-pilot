import type { Market } from "./types";

export type HistoryPoint = {
  t: number;
  prices: Record<string, string>;
  stale: string[]; // exchanges whose price here is older than the freshness limit
};
export type History = Record<string, HistoryPoint[]>; // symbol -> points, oldest first

export const MAX_POINTS = 600; // ten minutes at one snapshot per second
export const MAX_STALE_SECONDS = 120; // older prices leave a hole instead of a dashed line

/** Adds one market snapshot to the history. Pure: returns a new object.
 *
 * Fresh prices are kept, and prices up to two minutes old are kept and marked stale so the
 * chart can draw them dashed. Older ones are dropped. A snapshot older than the newest point
 * is ignored.
 */
export function addSnapshot(history: History, market: Market, maxPoints = MAX_POINTS): History {
  const t = Date.parse(market.time);
  if (Number.isNaN(t)) return history;

  const bySymbol: Record<string, { prices: Record<string, string>; stale: string[] }> = {};
  for (const row of market.prices) {
    if (!row.fresh && row.age_seconds > MAX_STALE_SECONDS) continue;
    const entry = bySymbol[row.symbol] ?? { prices: {}, stale: [] };
    entry.prices[row.exchange] = row.price;
    if (!row.fresh) entry.stale.push(row.exchange);
    bySymbol[row.symbol] = entry;
  }

  const next: History = { ...history };
  for (const [symbol, entry] of Object.entries(bySymbol)) {
    const points = history[symbol] ?? [];
    const last = points[points.length - 1];
    if (last && t < last.t) continue;
    const kept = last && last.t === t ? points.slice(0, -1) : points;
    next[symbol] = [...kept, { t, prices: entry.prices, stale: entry.stale }].slice(-maxPoints);
  }
  return next;
}