# Reconciliation (the Checker)

Compares our ledger with an exchange statement and lists every disagreement ("break").
It only reports. It never changes either side.

## Statement format (CSV, one exchange per file)
`trade_id,symbol,side,quantity,price,fee,fee_asset,executed_at`
- `fee_asset` is optional; a blank fee means 0.
- `executed_at` is ISO 8601 and must include a timezone (`2026-11-10T10:00:00Z`).
- Column names are matched ignoring case, spacing and order; extra columns are ignored.
- A file with any unreadable row is refused as a whole, with every bad line listed.
- Real exchange exports will each get a small adapter that produces this format.

## How trades are matched
By the exchange's own `trade_id`, within one exchange.
- Our trades on other exchanges are ignored.
- A statement trade of another exchange is an input error.
- A trade the statement lists must be in our ledger, whatever its time.
- Our trades OUTSIDE the period [start, end) that the statement does not list are not
  blamed; they are counted as "not checked".
- Our trades INSIDE the period that the statement does not list are breaks.

## Breaks
| Kind | Meaning |
|---|---|
| missing_in_ledger | the statement lists a trade we have no record of |
| missing_in_statement | we have a trade (inside the period) the statement does not list |
| duplicate_in_statement | the statement lists the same trade twice (the first is used) |
| symbol_mismatch | different coin pair |
| side_mismatch | buy vs sell |
| quantity_mismatch | different quantity |
| price_mismatch | different price |
| fee_mismatch | different fee amount, or the same amount in a different currency |
| time_drift | times differ by more than the tolerance (default 1 second) |

One trade can have several breaks. `difference` is statement minus ledger.

## Exactness
Quantity, price and fee must match exactly (2.0 and 2.00 are equal; 2 and 1.998 are not).
Only time has a tolerance. Per-field tolerances can be added if real statements need them.

## Proof
`scripts/inject_breaks.py` builds a day of trades, injects 20 known mistakes (every kind
of break) on 20 different trades, and checks that the Checker reports exactly those 20:
none missed, no false alarms. The test repeats this on 25 different random days.

## Not included yet
Per-exchange statement adapters, balance reconciliation (deposits and withdrawals),
partial matching by amount and time when IDs are missing, and suggested fixes.