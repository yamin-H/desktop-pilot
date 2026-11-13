# Redis Streams between ingestion and everything else

feeds -> [ingest: buffered XADD] -> Redis stream `ticks` -> consumer group `recorder` -> PostgreSQL
                                                         \-> API follower (XREAD) -> live dashboard

## Guarantees
- Publishing is at-least-once. Ingest keeps a bounded buffer and retries; a batch that fails
  halfway is sent again, so a tick can appear twice in the stream.
- The recorder worker acknowledges an entry ONLY after the database save is confirmed. It is
  therefore at-least-once too, and exactly-once IN THE DATABASE because saving ignores duplicates.
- A worker killed at any moment loses nothing:
  - before saving: its entries stay pending and are redone
  - after saving, before acknowledging: they are redone and counted as duplicates
- Recovery: a restarted worker re-reads its own pending entries; any worker claims entries
  idle for 30 seconds (XAUTOCLAIM). Fresh entries of a live worker are never taken.
- Unreadable entries go to `ticks:dead` and are acknowledged, so one bad entry never blocks.
- The stream is capped (about 200,000 entries). If a consumer is down longer than the cap covers,
  the oldest ticks are trimmed away; recovery counts them as `lost`.

## Consumers
- `recorder` group (durable): scripts/run_recorder.py. Run several copies with different --name.
- API follower (live only): seeds from the last 2000 entries, then reads new ones. No group: every
  follower sees every tick. Set USE_REDIS=true to use it; otherwise the API polls the database.

## Failure behaviour
- Redis down: ingest and the recorder retry with backoff and keep their buffers; ingest drops the
  newest ticks (and counts them) only if its buffer overflows. The API health shows "redis": "unreachable".
- Database down: the worker keeps entries unacknowledged and retries; nothing is lost while the
  stream still holds them.
- Feeds never wait for Redis.

## Tests (fault injection, against a real Redis)
kill before save, kill after save before ack, takeover by another worker, no stealing from a live
worker, poison entry, database outage, trimmed entry. Skipped if Redis is not running.

## Limits
- Stream order is publish order, not exchange-time order across exchanges.
- One recorder group; a second independent persistence target would be a second group.
- Redis persistence is AOF "everysec": a Redis crash can lose about a second of entries.