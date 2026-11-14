"use client";

import { useState } from "react";
import { buildChart } from "@/lib/chart";
import { compareDecimal, subtractDecimal } from "@/lib/decimal";
import { exchangeInfo } from "@/lib/exchanges";
import { withThousands } from "@/lib/format";
import type { HistoryPoint } from "@/lib/history";
import { useElementWidth } from "@/lib/hooks";

const HEIGHT = 280;
const TIP_WIDTH = 176;

function gapBetween(point: HistoryPoint, exchanges: string[]): string | null {
  const [first, second] = exchanges;
  const a = point.prices[first];
  const b = point.prices[second];
  if (a === undefined || b === undefined) return null;
  const order = compareDecimal(a, b);
  if (order === null) return null;
  return order >= 0 ? subtractDecimal(a, b) : subtractDecimal(b, a); // exact, as text
}

export default function GapChart({
  symbol,
  points,
  exchanges,
}: {
  symbol: string;
  points: HistoryPoint[];
  exchanges: string[];
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const chart = width > 0 ? buildChart(points, exchanges, { width, height: HEIGHT }) : null;
  const shown = chart && hover !== null ? chart.visible[hover] : undefined;
  const names = exchanges.map((id) => exchangeInfo(id).name).join(" and ");

  return (
    <div>
      <div className="chart" ref={ref}>
        {chart ? (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`Price of ${symbol} on ${names} over the last ${chart.startLabel.replace(" ago", "")}`}
            onPointerMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect();
              setHover(chart.nearest(event.clientX - box.left));
            }}
            onPointerLeave={() => setHover(null)}
          >
            {chart.ticks.map((tick, index) => (
              <g key={index}>
                <line className="grid" x1={chart.plot.left} x2={chart.plot.right} y1={tick.y} y2={tick.y} />
                <text x={chart.plot.left - 8} y={tick.y + 4} textAnchor="end">{tick.label}</text>
              </g>
            ))}
            <path className="gap-band" d={chart.gapPath} />
            {exchanges.map((id) => (
              <path key={id} className="series" d={chart.lines[id]} style={{ stroke: exchangeInfo(id).color }} />
            ))}
            <text x={chart.plot.left} y={HEIGHT - 6}>{chart.startLabel}</text>
            <text x={chart.plot.right} y={HEIGHT - 6} textAnchor="end">now</text>
            {shown ? (
              <g>
                <line className="cursor" x1={chart.x(shown.t)} x2={chart.x(shown.t)} y1={chart.plot.top} y2={chart.plot.bottom} />
                {exchanges.map((id) =>
                  shown.prices[id] === undefined ? null : (
                    <circle
                      key={id}
                      className="mark"
                      r={5}
                      cx={chart.x(shown.t)}
                      cy={chart.y(Number(shown.prices[id]))}
                      style={{ fill: exchangeInfo(id).color }}
                    />
                  ),
                )}
              </g>
            ) : null}
          </svg>
        ) : (
          <div className="chart-empty">Collecting prices. The chart appears after a few seconds.</div>
        )}
        {chart && shown ? (
          <div
            className="tip"
            style={{ left: Math.min(Math.max(chart.x(shown.t) - TIP_WIDTH / 2, 0), width - TIP_WIDTH) }}
          >
            <div className="muted">{new Date(shown.t).toISOString().slice(11, 19)} UTC</div>
            {exchanges.map((id) =>
              shown.prices[id] === undefined ? null : (
                <div className="tip-row" key={id}>
                  <span>
                    <span className="swatch" style={{ background: exchangeInfo(id).color }} />
                    {exchangeInfo(id).name}
                  </span>
                  <span>{withThousands(shown.prices[id])}</span>
                </div>
              ),
            )}
            {gapBetween(shown, exchanges) !== null ? (
              <div className="tip-row">
                <span>Gap</span>
                <span>{withThousands(gapBetween(shown, exchanges))}</span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="legend">
        {exchanges.map((id) => (
          <span key={id}>
            <span className="swatch" style={{ background: exchangeInfo(id).color }} />
            {exchangeInfo(id).name}
          </span>
        ))}
        {exchanges.length >= 2 ? (
          <span>
            <span className="band" />
            Gap between the first two
          </span>
        ) : null}
      </div>
    </div>
  );
}