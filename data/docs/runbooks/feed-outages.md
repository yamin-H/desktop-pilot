# Price feed outages

## Symptoms
The dashboard shows a stale price, or the recorder log shows repeated reconnect warnings. A feed is treated as dead when no message arrives for 30 seconds.

## What happens automatically
Feeds reconnect by themselves with growing pauses between attempts: 1 second, 2 seconds, 4 seconds, up to 30 seconds. The wait resets when a real message arrives.

## What to do
If one exchange stays down for more than ten minutes, check the exchange status page and note the outage in the desk log. Do not compare prices from a stale feed. Spread numbers ignore any price older than 30 seconds.

## Database trouble
If the database is unreachable, the recorder keeps ticks in memory and retries. If the buffer overflows, the newest ticks are dropped and counted. A non-zero dropped count must be reported.