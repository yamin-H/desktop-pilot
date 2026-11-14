export function niceScale(min: number, max: number, target = 4): { ticks: number[]; decimals: number } {
  const range = max - min;
  if (!(range > 0)) return { ticks: [min], decimals: 0 };
  const raw = range / target;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalized = raw / magnitude;
  const factor = normalized < 1.5 ? 1 : normalized < 3.5 ? 2 : normalized < 7.5 ? 5 : 10;
  const step = factor * magnitude;
  const ticks: number[] = [];
  for (let i = Math.ceil(min / step - 1e-9); i * step <= max + step * 1e-9; i += 1) {
    ticks.push(Number((i * step).toFixed(10)));
  }
  return { ticks, decimals: Math.max(0, -Math.floor(Math.log10(step) + 1e-9)) };
}

/** Moves `current` towards `target`; after `tauMs` it has covered about 63% of the distance. */
export function approach(current: number, target: number, dtMs: number, tauMs: number): number {
  if (!(dtMs > 0)) return current;
  const next = current + (target - current) * (1 - Math.exp(-dtMs / tauMs));
  return Math.abs(target - next) < 1e-9 * Math.max(1, Math.abs(target)) ? target : next;
}

/** The price range to draw: the data's range with generous padding, never absurdly tight. */
export function yDomain(values: number[]): [number, number] | null {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return null;
  const low = Math.min(...finite);
  const high = Math.max(...finite);
  const middle = (low + high) / 2;
  const minimumSpan = Math.max(Math.abs(middle) * 0.0004, 0.5);
  const span = Math.max((high - low) * 1.5, minimumSpan);
  return [middle - span / 2, middle + span / 2];
}

const TIME_STEPS_MS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600].map((seconds) => seconds * 1000);

/** Round clock times (multiples of a nice step) inside [from, to], about `target` of them. */
export function timeTicks(from: number, to: number, target = 6): number[] {
  const span = to - from;
  if (!(span > 0)) return [];
  const step = TIME_STEPS_MS.find((s) => span / s <= target) ?? TIME_STEPS_MS[TIME_STEPS_MS.length - 1];
  const ticks: number[] = [];
  for (let t = Math.ceil(from / step) * step; t <= to; t += step) ticks.push(t);
  return ticks;
}

export function formatClock(ms: number, withSeconds: boolean): string {
  return new Date(ms).toISOString().slice(11, withSeconds ? 19 : 16);
}

/** Index of the time closest to `target` in a sorted list, or null for an empty list. */
export function nearestIndex(times: number[], target: number): number | null {
  if (times.length === 0) return null;
  let low = 0;
  let high = times.length - 1;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (times[middle] < target) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(times[low - 1] - target) <= Math.abs(times[low] - target)) return low - 1;
  return low;
}

/** Keeps price tags from overlapping: pushes them apart by at least `minGap`, inside [top, bottom]. */
export function spreadTags(ys: number[], minGap: number, top: number, bottom: number): number[] {
  const order = ys.map((_, index) => index).sort((a, b) => ys[a] - ys[b]);
  const placed = order.map((index) => ys[index]);
  for (let i = 0; i < placed.length; i += 1) {
    placed[i] = Math.max(placed[i], i === 0 ? top : placed[i - 1] + minGap);
  }
  for (let i = placed.length - 1; i >= 0; i -= 1) {
    placed[i] = Math.min(placed[i], i === placed.length - 1 ? bottom : placed[i + 1] - minGap);
  }
  const result: number[] = new Array(ys.length);
  order.forEach((original, rank) => {
    result[original] = placed[rank];
  });
  return result;
}

const INK = "#16202e";

function luminance(hex: number): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel((hex >> 16) & 255) + 0.7152 * channel((hex >> 8) & 255) + 0.0722 * channel(hex & 255);
}

/** White or dark ink, whichever is easier to read on this colour (a #rrggbb string). */
export function readableText(background: string): string {
  const match = /^#?([0-9a-f]{6})$/i.exec(background.trim());
  if (!match) return "#ffffff";
  const l = luminance(parseInt(match[1], 16));
  const onWhite = 1.05 / (l + 0.05);
  const onInk = (l + 0.05) / (luminance(parseInt(INK.slice(1), 16)) + 0.05);
  return onInk > onWhite ? INK : "#ffffff";
}