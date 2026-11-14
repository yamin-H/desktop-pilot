"use client";

import { area, curveMonotoneX, line } from "d3-shape";
import { useEffect, useRef, useState } from "react";
import { ChartMotion, DISPLAY_LAG_MS } from "@/lib/engine";
import { exchangeInfo } from "@/lib/exchanges";
import { withThousands } from "@/lib/format";
import { gapText } from "@/lib/gap";
import type { HistoryPoint } from "@/lib/history";
import { formatClock, nearestIndex, niceScale, readableText, spreadTags, timeTicks, yDomain } from "@/lib/scale";
import { bandPoints, sampleAt, seriesFor, sliceWindow, splitRuns, type BandPoint, type SeriesPoint } from "@/lib/series";

const HEIGHT = 320;
const MARGIN = { top: 14, right: 92, bottom: 28, left: 12 };
const TIP_WIDTH = 184;
const LOOKAHEAD_MS = 2500; // samples just past the right edge keep the curve smooth up to it

type Props = {
  symbol: string;
  points: HistoryPoint[];
  exchanges: string[];
  connected: boolean;
  getNow: () => number;
  windowMs: number;
};

type Hover = { t: number; left: number; prices: Record<string, string>; stale: string[] };

type Colors = {
  grid: string; muted: string; band: string; surface: string; cursor: string;
  exchange: Record<string, string>;
};

function cssVar(element: HTMLElement, name: string): string {
  return getComputedStyle(element).getPropertyValue(name).trim() || "#888888";
}

function readColors(element: HTMLElement, exchanges: string[]): Colors {
  const exchange: Record<string, string> = {};
  for (const id of exchanges) exchange[id] = cssVar(element, exchangeInfo(id).cssVar);
  return {
    grid: cssVar(element, "--line"),
    muted: cssVar(element, "--muted"),
    band: cssVar(element, "--gap-fill"),
    surface: cssVar(element, "--surface"),
    cursor: cssVar(element, "--line-strong"),
    exchange,
  };
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

type Head = { id: string; t: number; value: number; point: SeriesPoint };

export default function LiveChart({ symbol, points, exchanges, connected, getNow, windowMs }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const pointer = useRef<number | null>(null);
  const latest = useRef({ points, exchanges, getNow, windowMs });
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    latest.current = { points, exchanges, getNow, windowMs };
  });

  useEffect(() => {
    const wrapper = box.current;
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!wrapper || !element || !context) return;
    const ctx = context;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const dark = window.matchMedia("(prefers-color-scheme: dark)");
    const fontFamily = getComputedStyle(wrapper).fontFamily;

    let colors = readColors(wrapper, []);
    let colorsKey = "";
    const refreshColors = () => {
      colorsKey = ""; // read the theme colours again on the next frame
    };
    dark.addEventListener("change", refreshColors);

    let width = 0;
    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      width = Math.floor(wrapper.clientWidth);
      element.width = Math.max(1, Math.round(width * ratio));
      element.height = Math.round(HEIGHT * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(wrapper);
    resize();

    const motion = new ChartMotion(latest.current.windowMs);
    let hoveredAt: number | null = null;
    let previous = performance.now();
    let frame = 0;

    const loop = (stamp: number) => {
      frame = requestAnimationFrame(loop);
      const dt = Math.min(stamp - previous, 100);
      previous = stamp;
      if (width <= MARGIN.left + MARGIN.right + 40) return;

      const input = latest.current;
      const key = input.exchanges.join(",");
      if (key !== colorsKey) {
        colors = readColors(wrapper, input.exchanges);
        colorsKey = key;
      }

      // Time, ranges and hover
      const animate = !reduced.matches;
      const lastSample = input.points[input.points.length - 1];
      const realNow = animate || !lastSample ? input.getNow() : lastSample.t + DISPLAY_LAG_MS;
      const pointerX = pointer.current;
      motion.advanceTime(dt, realNow, pointerX !== null, animate);
      motion.advanceWindow(dt, input.windowMs, animate);

      const plot = {
        left: MARGIN.left,
        right: width - MARGIN.right,
        top: MARGIN.top,
        bottom: HEIGHT - MARGIN.bottom,
      };
      const plotWidth = plot.right - plot.left;
      const plotHeight = plot.bottom - plot.top;
      const from = motion.now - motion.windowMs;
      const toX = (t: number) => plot.left + ((t - from) / motion.windowMs) * plotWidth;

      const visible = sliceWindow(input.points, from, motion.now + LOOKAHEAD_MS);
      const all = input.exchanges.map((id) => ({ id, series: seriesFor(visible, id) }));
      motion.advanceY(dt, yDomain(all.flatMap(({ series }) => series.map((p) => p.value))), animate);

      ctx.clearRect(0, 0, width, HEIGHT);

      // The sample under the pointer (for the crosshair and the tooltip)
      let sample: HistoryPoint | null = null;
      if (pointerX !== null) {
        const shown = visible.filter((p) => p.t >= from && p.t <= motion.now);
        const x = Math.min(Math.max(pointerX, plot.left), plot.right);
        const index = nearestIndex(shown.map((p) => p.t), from + ((x - plot.left) / plotWidth) * motion.windowMs);
        sample = index === null ? null : shown[index];
      }
      const sampleT = sample ? sample.t : null;
      if (sampleT !== hoveredAt) {
        hoveredAt = sampleT;
        setHover(
          sample
            ? {
                t: sample.t,
                left: Math.min(Math.max(toX(sample.t) - TIP_WIDTH / 2, 0), width - TIP_WIDTH),
                prices: sample.prices,
                stale: sample.stale,
              }
            : null,
        );
      }

      if (!motion.y || visible.length < 2) return;
      const [low, high] = motion.y;
      const toY = (value: number) => plot.top + (1 - (value - low) / (high - low)) * plotHeight;

      // The live end of each line: where the displayed moment sits on it
      const heads: Head[] = [];
      for (const { id, series } of all) {
        if (series.length === 0) continue;
        const t = Math.min(motion.now, series[series.length - 1].t);
        const found = sampleAt(series, t);
        if (found) heads.push({ id, t, value: found.value, point: found.point });
      }
      const tagYs = spreadTags(heads.map((h) => toY(h.value)), 22, plot.top + 10, plot.bottom - 10);

      // Grid and price labels
      ctx.font = `12px ${fontFamily}`;
      ctx.textBaseline = "middle";
      const scale = niceScale(low, high, 5);
      for (const value of scale.ticks) {
        const y = Math.round(toY(value)) + 0.5;
        if (y < plot.top || y > plot.bottom) continue;
        ctx.strokeStyle = colors.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(plot.left, y);
        ctx.lineTo(plot.right, y);
        ctx.stroke();
        if (tagYs.some((tagY) => Math.abs(tagY - y) < 13)) continue; // a tag covers this label
        ctx.fillStyle = colors.muted;
        ctx.textAlign = "left";
        ctx.fillText(
          value.toLocaleString("en-US", { minimumFractionDigits: scale.decimals, maximumFractionDigits: scale.decimals }),
          plot.right + 10,
          y,
        );
      }

      // Time labels slide with the chart
      ctx.textAlign = "center";
      ctx.fillStyle = colors.muted;
      for (const t of timeTicks(from, motion.now, 6)) {
        const x = toX(t);
        if (x < plot.left + 16 || x > plot.right - 16) continue;
        ctx.fillText(formatClock(t, motion.windowMs <= 180_000), x, HEIGHT - 10);
      }

      // Band and lines, clipped to the plot
      ctx.save();
      ctx.beginPath();
      ctx.rect(plot.left, plot.top - 6, plotWidth, plotHeight + 12);
      ctx.clip();

      if (input.exchanges.length >= 2) {
        ctx.beginPath();
        area<BandPoint>()
          .x((d) => toX(d.t))
          .y0((d) => toY(d.a))
          .y1((d) => toY(d.b))
          .defined((d) => d.fresh)
          .curve(curveMonotoneX)
          .context(ctx)(bandPoints(visible, input.exchanges[0], input.exchanges[1]));
        ctx.fillStyle = colors.band;
        ctx.fill();
      }

      const path = line<SeriesPoint>()
        .x((d) => toX(d.t))
        .y((d) => toY(d.value))
        .curve(curveMonotoneX)
        .context(ctx);
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      for (const { id, series } of all) {
        ctx.strokeStyle = colors.exchange[id] ?? colors.muted;
        for (const run of splitRuns(series)) {
          ctx.globalAlpha = run.stale ? 0.55 : 1;
          ctx.setLineDash(run.stale ? [5, 5] : []);
          ctx.beginPath();
          path(run.points);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
      ctx.restore();

      // Crosshair
      if (sample) {
        const x = toX(sample.t);
        ctx.strokeStyle = colors.cursor;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, plot.top);
        ctx.lineTo(x, plot.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const id of input.exchanges) {
          const text = sample.prices[id];
          if (text === undefined || !Number.isFinite(Number(text))) continue;
          ctx.beginPath();
          ctx.arc(x, toY(Number(text)), 5, 0, Math.PI * 2);
          ctx.fillStyle = colors.exchange[id] ?? colors.muted;
          ctx.fill();
          ctx.strokeStyle = colors.surface;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Live dots with a slow pulse
      const phase = (stamp / 1600) % 1;
      for (const head of heads) {
        const color = colors.exchange[head.id] ?? colors.muted;
        const x = toX(head.t);
        const y = toY(head.value);
        if (animate && pointerX === null && !head.point.stale) {
          ctx.beginPath();
          ctx.arc(x, y, 4 + 10 * phase, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.globalAlpha = 0.3 * (1 - phase);
          ctx.fill();
          ctx.globalAlpha = 1;
        }
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = head.point.stale ? colors.surface : color;
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Price tags on the right axis (exact prices from the data)
      ctx.font = `600 12px ${fontFamily}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      heads.forEach((head, index) => {
        const color = colors.exchange[head.id] ?? colors.muted;
        const label = withThousands(head.point.text);
        const w = Math.min(MARGIN.right - 10, ctx.measureText(label).width + 16);
        ctx.globalAlpha = head.point.stale ? 0.6 : 1;
        roundedRect(ctx, plot.right + 6, tagYs[index] - 10, w, 20, 5);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.fillStyle = readableText(color);
        ctx.fillText(label, plot.right + 14, tagYs[index] + 0.5);
        ctx.globalAlpha = 1;
      });
    };

    frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      dark.removeEventListener("change", refreshColors);
    };
  }, []);

  const names = exchanges.map((id) => exchangeInfo(id).name).join(" and ");
  const gap = hover ? gapText(hover.prices, hover.stale, exchanges) : null;

  return (
    <div className="chart" ref={box}>
      <canvas
        ref={canvas}
        role="img"
        aria-label={`Live price chart for ${symbol} on ${names}`}
        onPointerMove={(event) => {
          pointer.current = event.clientX - event.currentTarget.getBoundingClientRect().left;
        }}
        onPointerLeave={() => {
          pointer.current = null;
        }}
        onPointerCancel={() => {
          pointer.current = null;
        }}
      />
      {points.length < 2 ? (
        <div className="chart-note">Collecting prices. The chart appears after a few seconds.</div>
      ) : null}
      {!connected ? <div className="chart-flag">Disconnected. Reconnecting…</div> : null}
      {hover ? (
        <div className="tip" style={{ transform: `translateX(${hover.left}px)` }}>
          <div className="muted">{formatClock(hover.t, true)} UTC</div>
          {exchanges.map((id) =>
            hover.prices[id] === undefined ? null : (
              <div className="tip-row" key={id}>
                <span>
                  <span className="swatch" style={{ background: exchangeInfo(id).color }} />
                  {exchangeInfo(id).name}
                </span>
                <span className={hover.stale.includes(id) ? "stale" : ""}>
                  {withThousands(hover.prices[id])}
                  {hover.stale.includes(id) ? " (stale)" : ""}
                </span>
              </div>
            ),
          )}
          {gap !== null ? (
            <div className="tip-row">
              <span>Gap</span>
              <span>{withThousands(gap)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}