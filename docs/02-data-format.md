# Common data format

Every exchange sends data in its own shape. We convert it ONCE, at the edge
(`ingestion/`), into the shapes below. Nothing else in the system sees
exchange-specific data.

## Rules
1. Money is an exact `Decimal`. Floats are rejected.
2. Every timestamp is timezone-aware and stored in UTC.
3. Symbols look like `BTC/USDT` (BASE/QUOTE, upper case).
4. Models are immutable (frozen) and reject unknown fields.

## PriceTick
| Field | Meaning |
|---|---|
| exchange | which exchange (binance, kraken, bybit) |
| symbol | coin pair, e.g. BTC/USDT |
| price | last traded price, > 0 |
| exchange_time | when the exchange says it happened (UTC) |
| received_time | when our program received it (UTC) |

## Trade
| Field | Meaning |
|---|---|
| exchange | which exchange |
| trade_id | the exchange's own ID for this trade |
| symbol | coin pair |
| side | buy or sell |
| quantity | amount of the base coin, > 0 |
| price | price per unit, > 0 |
| fee | fee paid, >= 0 |
| fee_asset | coin the fee was paid in (optional) |
| executed_at | when the trade happened (UTC) |

`notional` = quantity x price.
`dedupe_key` = (exchange, trade_id). Same key means same trade, so saving it
twice must change nothing.