"use client";

import { motion } from "motion/react";
import { useMemo, useState } from "react";
import Amount from "./Amount";
import ExchangeTag from "./ExchangeTag";
import LiveChart from "./LiveChart";
import { useMarket } from "./MarketProvider";
import Segmented from "./Segmented";
import { exchangeInfo } from "@/lib/exchanges";
import { ageText, withThousands } from "@/lib/format";
import type { PriceRow } from "@/lib/types";

const RANGES = { "1m": 60_000, "3m": 180_000, "10m": 600_000 } as const;
type Range = keyof typeof RANGES;

function Quote({ exchange, row }: { exchange: string; row: PriceRow | undefined }) {
  const info = exchangeInfo(exchange);
  const stale = row !== undefined && !row.fresh;
  return (
    <div className="quote">
      <div className="quote-name">
        <span className="swatch" style={{ background: info.color }} />
        {info.name}
      </div>
      <div className={`price-big ${stale ? "dim" : ""}`}>
        <Amount text={row?.price} />
      </div>
      <div className={`small ${stale ? "stale" : "muted"}`}>
        {!row
          ? "No price yet"
          : row.fresh
            ? `Updated ${ageText(row.age_seconds)} ago`
            : `Stale: last trade ${ageText(row.age_seconds)} ago`}
      </div>
    </div>
  );
}

function Empty({ connected }: { connected: boolean }) {
  return (
    <section className="panel empty">
      <h2>{connected ? "No prices yet" : "Can't reach the API"}</h2>
      {connected ? (
        <p>
          Start the price feeds with <code>uv run python scripts/record_prices.py</code>, or with{" "}
          <code>scripts/run_ingest.py</code> when <code>USE_REDIS=true</code>.
        </p>
      ) : (
        <p>
          Start it with <code>make api</code>. This page reconnects by itself.
        </p>
      )}
    </section>
  );
}

export default function MarketView() {
  const { market, history, connected, getNow } = useMarket();
  const [chosen, setChosen] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("3m");

  const symbols = useMemo(
    () => Array.from(new Set((market?.prices ?? []).map((p) => p.symbol))).sort(),
    [market],
  );
  const symbol = chosen && symbols.includes(chosen) ? chosen : symbols[0];

  if (!market || !symbol) {
    return (
      <>
        <div className="page-head"><h1>Market</h1></div>
        <Empty connected={connected} />
      </>
    );
  }

  const rows = market.prices.filter((p) => p.symbol === symbol);
  const exchanges = rows.map((p) => p.exchange).sort();
  const spread = market.spreads.find((s) => s.symbol === symbol);
  const quote = symbol.split("/")[1];

  return (
    <>
      <div className="page-head">
        <h1>Market</h1>
        <Segmented
          label="Coin pair"
          value={symbol}
          options={symbols.map((s) => ({ value: s, label: s }))}
          onChange={setChosen}
        />
      </div>

      <div className="stack">
        <section className="panel hero" aria-label={`${symbol} on each exchange`}>
          <div className="hero-top">
            {exchanges.map((exchange) => (
              <Quote key={`${symbol}-${exchange}`} exchange={exchange} row={rows.find((r) => r.exchange === exchange)} />
            ))}
            <div className="gap">
              <div className="quote-name">Gap between exchanges</div>
              {spread ? (
                <>
                  <div className="price-big">
                    <Amount text={spread.amount} /> <span className="unit">{quote}</span>
                  </div>
                  <div className="small muted">
                    {spread.percent}% of the lower price. {exchangeInfo(spread.high.exchange).name} is higher.
                  </div>
                </>
              ) : (
                <>
                  <div className="price-big unknown">—</div>
                  <div className="small muted">
                    Needs a price under {market.max_age_seconds}s old from two exchanges.
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="chart-bar">
            <div className="legend">
              {exchanges.map((id) => (
                <span key={id}>
                  <span className="swatch" style={{ background: exchangeInfo(id).color }} />
                  {exchangeInfo(id).name}
                </span>
              ))}
              {exchanges.length >= 2 ? (
                <span><span className="band" />Gap between the first two</span>
              ) : null}
              <span><span className="dash" />Last known price, no trade in {market.max_age_seconds} s</span>
            </div>
            <Segmented
              label="Time range"
              value={range}
              onChange={setRange}
              options={[
                { value: "1m", label: "1 min" },
                { value: "3m", label: "3 min" },
                { value: "10m", label: "10 min" },
              ]}
            />
          </div>

          <motion.div key={symbol} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.35 }}>
            <LiveChart
              symbol={symbol}
              points={history[symbol] ?? []}
              exchanges={exchanges}
              connected={connected}
              getNow={getNow}
              windowMs={RANGES[range]}
            />
          </motion.div>
        </section>

        <div className="two">
          <section className="panel">
            <div className="panel-head"><h2>Latest prices</h2></div>
            <div className="scroll">
              <table className="table">
                <thead>
                  <tr><th>Exchange</th><th>Pair</th><th className="num">Price</th><th>Updated</th></tr>
                </thead>
                <tbody>
                  {market.prices.map((p) => (
                    <tr key={`${p.exchange}-${p.symbol}`}>
                      <td><ExchangeTag id={p.exchange} /></td>
                      <td>{p.symbol}</td>
                      <td className="num">{withThousands(p.price)}</td>
                      <td>
                        <span className="cell-status">
                          <span className={`dot ${p.fresh ? "ok" : "warn"}`} aria-hidden="true" />
                          {p.fresh ? `${ageText(p.age_seconds)} ago` : `Stale, ${ageText(p.age_seconds)} ago`}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><h2>Gap by pair</h2></div>
            {market.spreads.length === 0 ? (
              <p className="note" style={{ padding: "0 20px 16px" }}>
                No gap to show yet. It needs a fresh price from two exchanges for the same pair.
              </p>
            ) : (
              <div className="scroll">
                <table className="table">
                  <thead>
                    <tr><th>Pair</th><th>Higher</th><th>Lower</th><th className="num">Gap</th><th className="num">Gap %</th></tr>
                  </thead>
                  <tbody>
                    {market.spreads.map((s) => (
                      <tr key={s.symbol}>
                        <td>{s.symbol}</td>
                        <td>{exchangeInfo(s.high.exchange).name}</td>
                        <td>{exchangeInfo(s.low.exchange).name}</td>
                        <td className="num">{withThousands(s.amount)}</td>
                        <td className="num">{s.percent}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <p className="note">
          Gaps compare last trade prices. They ignore fees, trade size and transfer time, so treat
          them as a monitoring signal, not a profit estimate. The chart shows about a second behind
          real time so every line is drawn between known samples.
        </p>
      </div>
    </>
  );
}