import type { HistoryPoint } from "./history";

// Prices arrive as exact text. Here they become numbers ONLY to decide where to draw;
// no number from this file is ever shown as an amount.

export type Margin = { top: number; right: number; bottom: number; left: number };
export type ChartOptions = {
  width: number;
  height: number;
  windowMs?: number;
  margin?: Partial<Margin>;
};

export type ChartGeometry = {
  visible: HistoryPoint[];
  plot: { left: number; right: number; top: number; bottom: number };
  lines: Record<string, string>; // SVG path per exchange
  gapPath: string; // the shaded band between the first two exchanges
  ticks: { y: number; label: string }[];
  startLabel: string;
  x: (t: number) => number;
  y: (value: number) => number;
  nearest: (px: number) => number | null; // index into `visible`, or null outside the plot
};

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

export function spanLabel(ms: number): string {
  const seconds = Math.round(ms / 1000);
  return seconds < 90 ? `${seconds} s ago` : `${Math.round(seconds / 60)} min ago`;
}

const num = (value: string | undefined): number => (value === undefined ? NaN : Number(value));

export function buildChart(
  points: HistoryPoint[],
  exchanges: string[],
  options: ChartOptions,
): ChartGeometry | null {
  const { width, height, windowMs = 180_000 } = options;
  const margin: Margin = { top: 12, right: 12, bottom: 24, left: 64, ...options.margin };
  if (points.length < 2 || width <= margin.left + margin.right || height <= margin.top + margin.bottom) {
    return null;
  }

  const end = points[points.length - 1].t;
  const visible = points.filter((p) => p.t >= end - windowMs);
  if (visible.length < 2) return null;
  const start = visible[0].t;
  const span = Math.max(end - start, 1);

  const values: number[] = [];
  for (const p of visible) {
    for (const exchange of exchanges) {
      const value = num(p.prices[exchange]);
      if (Number.isFinite(value)) values.push(value);
    }
  }
  if (values.length === 0) return null;

  let low = Math.min(...values);
  let high = Math.max(...values);
  const pad = high === low ? Math.max(Math.abs(low) * 0.0005, 0.5) : (high - low) * 0.15;
  low -= pad;
  high += pad;

  const plot = {
    left: margin.left,
    right: width - margin.right,
    top: margin.top,
    bottom: height - margin.bottom,
  };
  const plotWidth = plot.right - plot.left;
  const plotHeight = plot.bottom - plot.top;
  const x = (t: number) => plot.left + ((t - start) / span) * plotWidth;
  const y = (value: number) => plot.top + (1 - (value - low) / (high - low)) * plotHeight;
  const at = (n: number) => n.toFixed(1);

  const lines: Record<string, string> = {};
  for (const exchange of exchanges) {
    let path = "";
    let pen = false; // a missing price lifts the pen, so a feed outage shows as a break
    for (const p of visible) {
      const value = num(p.prices[exchange]);
      if (!Number.isFinite(value)) {
        pen = false;
        continue;
      }
      path += `${pen ? "L" : "M"}${at(x(p.t))},${at(y(value))}`;
      pen = true;
    }
    lines[exchange] = path;
  }

  let gapPath = "";
  const [first, second] = exchanges;
  if (first && second) {
    let run: { x: number; a: number; b: number }[] = [];
    const flush = () => {
      if (run.length >= 2) {
        const forward = run.map((r) => `${at(r.x)},${at(r.a)}`).join("L");
        const back = [...run].reverse().map((r) => `${at(r.x)},${at(r.b)}`).join("L");
        gapPath += `M${forward}L${back}Z`;
      }
      run = [];
    };
    for (const p of visible) {
      const a = num(p.prices[first]);
      const b = num(p.prices[second]);
      if (Number.isFinite(a) && Number.isFinite(b)) run.push({ x: x(p.t), a: y(a), b: y(b) });
      else flush();
    }
    flush();
  }

  const scale = niceScale(low, high, 4);
  const ticks = scale.ticks.map((value) => ({
    y: y(value),
    label: value.toLocaleString("en-US", {
      minimumFractionDigits: scale.decimals,
      maximumFractionDigits: scale.decimals,
    }),
  }));

  const nearest = (px: number): number | null => {
    if (px < plot.left - 8 || px > plot.right + 8) return null;
    const t = start + ((px - plot.left) / plotWidth) * span;
    let best = 0;
    let distance = Infinity;
    visible.forEach((p, index) => {
      const d = Math.abs(p.t - t);
      if (d < distance) {
        distance = d;
        best = index;
      }
    });
    return best;
  };

  return { visible, plot, lines, gapPath, ticks, startLabel: spanLabel(end - start), x, y, nearest };
}