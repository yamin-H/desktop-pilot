"use client";

import { ageText, withThousands } from "@/lib/format";
import { useMarketStream } from "@/lib/hooks";

export default function MarketPanel() {
  const { market, connected } = useMarketStream();

  return (
    <section>
      <h2>
        Market <span className={connected ? "badge live" : "badge off"}>{connected ? "live" : "reconnecting…"}</span>
      </h2>
      {!market || market.prices.length === 0 ? (
        <p className="muted">Waiting for prices. Is the recorder running?</p>
      ) : (
        <>
          <h3>Gap between exchanges</h3>
          {market.spreads.length === 0 ? (
            <p className="muted">
              No gap to show: it needs a fresh price (under {market.max_age_seconds}s old) from two exchanges.
            </p>
          ) : (
            <table>
              <thead>
                <tr><th>Pair</th><th>Higher</th><th>Lower</th><th className="num">Gap</th><th className="num">Gap %</th></tr>
              </thead>
              <tbody>
                {market.spreads.map((s) => (
                  <tr key={s.symbol}>
                    <td>{s.symbol}</td>
                    <td>{s.high.exchange} <span className="num">{withThousands(s.high.price)}</span></td>
                    <td>{s.low.exchange} <span className="num">{withThousands(s.low.price)}</span></td>
                    <td className="num">{withThousands(s.amount)}</td>
                    <td className="num">{s.percent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h3>Latest prices</h3>
          <table>
            <thead>
              <tr><th>Exchange</th><th>Pair</th><th className="num">Price</th><th className="num">Age</th></tr>
            </thead>
            <tbody>
              {market.prices.map((p) => (
                <tr key={`${p.exchange}-${p.symbol}`} className={p.fresh ? "" : "stale"}>
                  <td>{p.exchange}</td>
                  <td>{p.symbol}</td>
                  <td className="num">{withThousands(p.price)}</td>
                  <td className="num">{ageText(p.age_seconds)}{p.fresh ? "" : " (stale)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            The gap compares last trade prices. It ignores fees, trade size and transfer time, so it
            is a monitoring number, not a profit claim.
          </p>
        </>
      )}
    </section>
  );
}