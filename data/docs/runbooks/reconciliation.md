# Reconciliation runbook

How the desk checks its own records against an exchange statement.

## When to reconcile
Reconcile every exchange once a day, after the statement for the previous UTC day is available. Always pass an explicit period. The start is included and the end is excluded.

## Missing in ledger
A missing_in_ledger break means the exchange statement lists a trade we never recorded. First check whether our price feed or recorder was down at that time. Then ask the exchange to confirm the trade ID. Never add the trade by hand without a second person's approval.

## Missing in statement
A missing_in_statement break means we recorded a trade that the statement does not list. Check the statement period first: a trade just outside it is not an error. If the trade is inside the period, contact the exchange.

## Quantity, price and fee mismatches
Amounts must match exactly. A quantity that differs by the size of a fee usually means the fee was taken in coins instead of USDT. Record the difference and escalate it to the desk lead. Do not change the stored trade.

## Time drift
Differences up to one second are normal clock drift and are ignored. Larger differences are reported as time_drift and should be checked against the exchange's own timestamp.