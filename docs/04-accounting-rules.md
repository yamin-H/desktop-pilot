# Accounting rules

How positions and profit are calculated. Every rule is tested.

## Positions
- One position per (exchange, coin pair). Coins on one exchange cannot be sold on another.
- Cost method: AVERAGE COST. Cost per coin = total cost of coins held / coins held.
  Selling removes coins at the current average, so the average itself does not change.
- Selling everything removes the exact remaining cost, so no rounding crumbs are left.

## Fees (already included in cost and profit)
- Fee in the quote currency (USDT) on a buy: added to the cost.
- Fee in the quote currency on a sell: subtracted from the proceeds.
- Fee in coins on a buy: fewer coins arrive for the same money.
- Fee in coins on a sell: the fee coins leave the position too (quantity + fee).
- Fee in any other currency (e.g. BNB), or a fee with no currency: REFUSED.
  Converting it needs that currency's price at that time, and we do not guess.

## Profit
- Realized profit: locked in by sales. Each sale is kept as a RealizedEvent
  (with its time), so profit for a period can be added up later.
- Unrealized profit: coins held x current price - their cost. The current price
  is always supplied by the caller. No price means UNKNOWN (None), never zero.
- Totals are kept per quote currency. USDT and USD are never added together.
- One missing price makes that currency's unrealized total unknown.

## Refused instead of guessed
- The same trade given twice (profit would be counted twice).
- A sale of more coins than held (a trade or deposit must be missing).
- A fee that cannot be placed.

## Order
Trades are processed by time. For trades at the exact same time, trade ID order is
used as a stable tie-break. It is arbitrary, so a purchase and sale at the same
instant should be avoided in data we control.

## Not included yet
Deposits and withdrawals, tax rules, funding fees, FIFO, and the exit fee that
selling everything now would cost.

## Precision
Python's Decimal keeps 28 significant digits. Only division can round, by about
a trillionth of a trillionth of a cent. Amounts are rounded only for display.