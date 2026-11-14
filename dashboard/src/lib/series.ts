import type { HistoryPoint } from "./history";

export type SeriesPoint = { t: number; value: number; text: string; stale: boolean };
export type Run = { stale: boolean; points: SeriesPoint[] };
export type BandPoint = { t: number; a: number; b: number; fresh: boolean };

/** The points inside [from, to], plus one point before `from` so a line enters from the left edge. */
export function sliceWindow<T extends { t: number }>(items: T[], from: number, to: number): T[] {
  let start = 0;
  while (start < items.length && items[start].t < from) start += 1;
  let end = start;
  while (end < items.length && items[end].t <= to) end += 1;
  return items.slice(Math.max(0, start - 1), end);
}

/** One exchange's price over time. Numbers are for drawing; `text` keeps the exact price. */
export function seriesFor(points: HistoryPoint[], exchange: string): SeriesPoint[] {
  const result: SeriesPoint[] = [];
  for (const point of points) {
    const text = point.prices[exchange];
    if (text === undefined) continue;
    const value = Number(text);
    if (!Number.isFinite(value)) continue;
    result.push({ t: point.t, value, text, stale: point.stale.includes(exchange) });
  }
  return result;
}

/** Splits a series where "fresh" and "stale" alternate. A run starts with the previous point,
 *  so the pieces join up without gaps. */
export function splitRuns(series: SeriesPoint[]): Run[] {
  const runs: Run[] = [];
  let current: Run | null = null;
  series.forEach((point, index) => {
    if (current === null || current.stale !== point.stale) {
      const previous = series[index - 1];
      current = { stale: point.stale, points: previous ? [previous, point] : [point] };
      runs.push(current);
    } else {
      current.points.push(point);
    }
  });
  return runs;
}

/** The shaded gap between two exchanges. `fresh` is false where either price is missing or stale. */
export function bandPoints(points: HistoryPoint[], first: string, second: string): BandPoint[] {
  return points.map((point) => {
    const a = Number(point.prices[first]);
    const b = Number(point.prices[second]);
    const present =
      point.prices[first] !== undefined &&
      point.prices[second] !== undefined &&
      Number.isFinite(a) &&
      Number.isFinite(b);
    if (!present) return { t: point.t, a: 0, b: 0, fresh: false };
    return {
      t: point.t,
      a,
      b,
      fresh: !point.stale.includes(first) && !point.stale.includes(second),
    };
  });
}

/** The line's value at time t (interpolated between samples) and the sample at or before t.
 *  Null before the first sample. After the last sample the last value is held. */
export function sampleAt(
  series: SeriesPoint[],
  t: number,
): { value: number; point: SeriesPoint } | null {
  if (series.length === 0 || t < series[0].t) return null;
  let index = series.length - 1;
  while (index > 0 && series[index].t > t) index -= 1;
  const point = series[index];
  const next = series[index + 1];
  if (!next || next.t === point.t) return { value: point.value, point };
  const fraction = (t - point.t) / (next.t - point.t);
  return { value: point.value + (next.value - point.value) * fraction, point };
}