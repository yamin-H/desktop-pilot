"use client";

import ExchangeTag from "./ExchangeTag";
import { signClass, signed, utcText, withThousands } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { PnlResponse, PnlTotals, TradesResponse } from "@/lib/types";
import Amount from "./Amount";

function Summary({ totals }: { totals: PnlTotals }) {
  const missing = totals.missing_prices;
  return (
    <section className="panel summary" aria-label={`Profit in ${totals.quote_currency}`}>
      <div>
        <div className="quote-name">Total profit</div>
        <div className={`price-big ${signClass(totals.total_pnl)}`}>
          <Amount text={totals.total_pnl} signed /> <span className="unit">{totals.quote_currency}</span>
        </div>
      </div>
      <div className="equation">
        <span>Realized <strong className={signClass(totals.realized_pnl)}>{signed(totals.realized_pnl)}</strong></span>
        <span aria-hidden="true">+</span>
        <span>Unrealized <strong className={signClass(totals.unrealized_pnl)}>{signed(totals.unrealized_pnl)}</strong></span>
      </div>
      {missing.length > 0 ? (
        <p className="small stale warning">
          Unrealized profit is unknown: there is no recorded price for {missing.join(", ")}.
        </p>
      ) : null}
    </section>
  );
}

export default function PortfolioView() {
  const pnl = usePolling<PnlResponse>("/api/pnl", 10_000);
  const trades = usePolling<TradesResponse>("/api/trades?limit=10", 15_000);

  return (
    <>
      <div className="page-head"><h1>Portfolio</h1></div>
      <div className="stack">
        {pnl.error ? <p className="error">{pnl.error}</p> : null}
        {!pnl.data ? (
          <section className="panel empty"><p>Loading positions…</p></section>
        ) : pnl.data.positions.length === 0 ? (
          <section className="panel empty">
            <h2>No trades yet</h2>
            <p>Load the sample trades with <code>uv run python scripts/seed_trades.py</code>.</p>
          </section>
        ) : (
          <>
            {pnl.data.totals.map((totals) => (
              <Summary key={totals.quote_currency} totals={totals} />
            ))}

            <section className="panel">
              <div className="panel-head">
                <h2>Positions</h2>
                <p>Average-cost method. A dash means unknown, not zero.</p>
              </div>
              <div className="scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Exchange</th><th>Pair</th><th className="num">Held</th><th className="num">Average cost</th>
                      <th className="num">Price</th><th className="num">Realized</th><th className="num">Unrealized</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pnl.data.positions.map((p) => {
                      const closed = p.quantity === "0";
                      return (
                        <tr key={`${p.exchange}-${p.symbol}`} className={closed ? "closed" : ""}>
                          <td><ExchangeTag id={p.exchange} /></td>
                          <td>{p.symbol}</td>
                          <td className="num">{closed ? "Closed" : withThousands(p.quantity)}</td>
                          <td className="num">{withThousands(p.average_cost)}</td>
                          <td className={`num ${p.price_is_stale ? "stale" : ""}`}>
                            {withThousands(p.price)}
                            {p.price_is_stale ? " (stale)" : ""}
                          </td>
                          <td className={`num ${signClass(p.realized_pnl)}`}>{signed(p.realized_pnl)}</td>
                          <td className={`num ${signClass(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}

        <section className="panel">
          <div className="panel-head">
            <h2>Recent trades</h2>
            {trades.data ? <p>Showing {trades.data.shown} of {trades.data.total_matching}. All trades are made up.</p> : null}
          </div>
          {trades.error ? <p className="error" style={{ padding: "0 20px 16px" }}>{trades.error}</p> : null}
          <div className="scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th><th>Exchange</th><th>Trade</th><th>Side</th><th>Pair</th>
                  <th className="num">Quantity</th><th className="num">Price</th><th className="num">Fee</th>
                </tr>
              </thead>
              <tbody>
                {(trades.data?.trades ?? []).map((t) => (
                  <tr key={`${t.exchange}-${t.trade_id}`}>
                    <td>{utcText(t.time)}</td>
                    <td><ExchangeTag id={t.exchange} /></td>
                    <td>{t.trade_id}</td>
                    <td>{t.side === "buy" ? "Buy" : "Sell"}</td>
                    <td>{t.symbol}</td>
                    <td className="num">{withThousands(t.quantity)}</td>
                    <td className="num">{withThousands(t.price)}</td>
                    <td className="num">{withThousands(t.fee)}{t.fee_asset ? ` ${t.fee_asset}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}