"use client";

import { signClass, withThousands } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { PnlResponse } from "@/lib/types";

export default function PnlPanel() {
  const { data, error } = usePolling<PnlResponse>("/api/pnl", 10_000);

  return (
    <section>
      <h2>Positions and profit</h2>
      {error ? <p className="error">{error}</p> : null}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : data.positions.length === 0 ? (
        <p className="muted">No trades yet.</p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Exchange</th><th>Pair</th><th className="num">Held</th><th className="num">Avg cost</th>
                <th className="num">Price</th><th className="num">Realized</th><th className="num">Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p) => (
                <tr key={`${p.exchange}-${p.symbol}`}>
                  <td>{p.exchange}</td>
                  <td>{p.symbol}</td>
                  <td className="num">{withThousands(p.quantity)}</td>
                  <td className="num">{withThousands(p.average_cost)}</td>
                  <td className={`num ${p.price_is_stale ? "stale" : ""}`}>
                    {withThousands(p.price)}{p.price_is_stale ? " (stale)" : ""}
                  </td>
                  <td className={`num ${signClass(p.realized_pnl)}`}>{withThousands(p.realized_pnl)}</td>
                  <td className={`num ${signClass(p.unrealized_pnl)}`}>{withThousands(p.unrealized_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.totals.map((t) => (
            <p key={t.quote_currency} className="totals">
              <strong>{t.quote_currency}</strong>: realized{" "}
              <span className={signClass(t.realized_pnl)}>{withThousands(t.realized_pnl)}</span>, unrealized{" "}
              <span className={signClass(t.unrealized_pnl)}>{withThousands(t.unrealized_pnl)}</span>, total{" "}
              <span className={signClass(t.total_pnl)}>{withThousands(t.total_pnl)}</span>
              {t.missing_prices.length > 0 ? (
                <span className="muted"> (unknown: no price for {t.missing_prices.join(", ")})</span>
              ) : null}
            </p>
          ))}
          <p className="muted small">A dash means unknown, not zero. Paper trades, average-cost method.</p>
        </>
      )}
    </section>
  );
}