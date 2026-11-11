# Design decisions

## Feeds reconnect forever, with exponential backoff and jitter
Connections drop in normal operation. Each failure doubles the wait (capped),
with random spread so many clients don't retry in lockstep. The wait resets
only after a real message arrives, not after merely connecting.

## A silent connection counts as a dead one
A socket can look open while nothing flows. If no message arrives within
`stale_after` seconds, we drop it and reconnect.

## Only connection errors are retried
`retry_on` lists the errors that mean "try again". Anything else is a bug in
our own code and crashes loudly instead of looping forever.

## One bad message never kills a connection
Unreadable messages are counted and skipped.

## Stopping a feed = cancelling its task
No custom stop flag. Cancelling closes the connection cleanly.


## Binance: the public trade stream is our price source
One message per trade, no API key needed. Each message becomes one PriceTick.
We keep the trade time (`T`) as `exchange_time`, not the message time.

## Symbols are translated from an explicit list
`BTCUSDT` cannot be split into base and quote reliably. A feed is created with
the symbols we want (`BTC/USDT`) and builds its translation table from them.
A symbol we did not ask for is treated as an unreadable message.

## Binance connections last at most 24 hours
Binance closes every connection after 24 hours. Normal reconnect handles it.


## Compare like with like: USDT on both exchanges
Binance quotes in USDT and Kraken mostly in USD. Comparing them would mix real
exchange gaps with the USD/USDT difference and create fake gaps. We subscribe to
Kraken's BTC/USDT and ETH/USDT so both sides quote the same asset.

## Kraken: subscribe after connecting, and again after every reconnect
Unlike Binance, Kraken needs a subscribe message. A reconnect is a new
connection, so `connect()` always subscribes. Tested against a fake server.

## Kraken: live trades only
We turn the snapshot off, and the parser also ignores snapshot messages, so
old trades are never mistaken for live prices.

## Kraken: batches are all or nothing
One message can hold several trades. If any trade in it is unreadable, the
whole message is skipped and counted as a parse error.

## Kraken: a refused subscription is loud
A `success: false` reply becomes a warning, instead of silently waiting for
prices that never come.