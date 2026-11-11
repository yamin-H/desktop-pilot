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


## Spreads use last trade prices: a monitoring number, not a profit claim
The gap is between the last trade on each exchange. It ignores trading fees,
the size we could actually trade, and the time needed to move coins. Realistic
numbers will use order books (best bid/ask) later.

## Old prices are never compared
A price older than `max_age` (30s) is left out of the gap calculation. Age is
measured on our own clock (when we received the tick), so clock differences
between us and the exchange do not matter.

## An older tick never replaces a newer one
After a reconnect, messages can arrive out of order. The board compares the
exchange's own timestamps and keeps the newer price.

## One gap per coin pair: the widest one
With more than two exchanges, the board reports the most expensive exchange
against the cheapest. Equal prices still give two different exchanges.

## All feeds run in one TaskGroup
Connection errors are handled inside each feed. A real bug in any feed stops all
of them and is raised, instead of leaving the system half-working in silence.


## Database: TimescaleDB on PostgreSQL 17, local only
Prices are time-series data; TimescaleDB stores them in one-day chunks. The image
is pinned to PostgreSQL 17 (PostgreSQL 18 images moved the data directory). The
container is bound to 127.0.0.1 only. The plain TimescaleDB image does not include
pgvector; we will choose how to add it when we reach document search.

## Money in the database is `numeric`, accessed through asyncpg
`numeric` is exact and maps to Python's `Decimal`, so no price or amount ever
passes through a float.

## A price record is identified by (exchange, symbol, exchange_time, price)
PriceTick has no trade ID, so this is the duplicate rule for the prices table.
Trade-off: two different trades in the same millisecond at the same price become
one row. That is fine for a price history, because we do not store volume. The
trades table will use the exchange's own trade_id, where exactness matters.

## Migrations are plain numbered SQL files
Each runs in its own transaction and is recorded with a checksum. Editing an
applied migration is refused: add a new one instead. An advisory lock stops two
runners from migrating at the same time.

## Tests run on their own database
`deskpilot_test` is created fresh each test run, so real data is never touched.
If PostgreSQL is not running, database tests are skipped with a clear message.
(When we add CI, we will make them required instead.)


## The recorder saves in batches
A batch is saved at 500 ticks or 1 second after its first tick, whichever comes
first. One database round trip per tick would be far slower.

## Feeds never wait for the database
`Recorder.on_tick` only puts the tick in a buffer. If the buffer is full (50,000),
the newest tick is dropped and counted (`dropped_count`), and a warning is logged.
Trade-off: a database outage longer than the buffer loses ticks, but a slow
database can never stall a feed and get us disconnected.

## Database trouble is retried, bugs are not
Connection errors are retried forever with backoff, keeping the same batch.
Anything else crashes loudly, like in the feeds.

## Retrying and re-saving is safe because saving is duplicate-safe
If shutdown interrupts a save, we cannot know whether it finished. The batch is
kept until a save is confirmed and re-saved by `drain()`; copies are ignored.

## Shutdown drains the buffer
After `run()` is cancelled, `drain()` saves everything still waiting.

## Duplicates are counted
`duplicate_count` is not a sign of trouble: two trades in the same millisecond at
the same price share one record (see the prices-table decision).

## The recorder is called directly for now
Redis Streams will later sit between ingestion and storage. The recorder's
`on_tick` interface should not need to change.


## The ledger never overwrites and never hides a changed trade
Same ID and same content is a duplicate and is ignored. Same ID with different
content is a conflict: the stored trade stays, the differing fields are reported
and logged. Silently ignoring it would keep wrong data unnoticed; overwriting
would destroy evidence. The reconciliation engine will build on this.

## Trades are a normal table, saved immediately
Trades are rare compared with prices, so there is no hypertable and no batching.
A plain table allows the exchange's trade_id to be a simple primary key.

## The database repeats the model's rules
CHECK constraints refuse zero quantities, negative fees and unknown sides, even
though the Trade model already validates them. The database is the last defence.

## Paper trades
Sample trades have fixed `PAPER-` IDs and fixed times, so seeding is repeatable.
Fees use mixed currencies on purpose (BTC and USDT), because the profit
calculation must handle them.