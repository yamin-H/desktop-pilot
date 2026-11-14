# Benchmarks

`uv run python scripts/benchmark.py --repeat 3 --markdown`

## What is measured
| Stage | Meaning |
|---|---|
| parse | raw Binance / Kraken messages -> ticks, per second (CPU only) |
| publish to Redis | ticks per second into the stream, in batches of 500 |
| Redis to PostgreSQL | ticks per second through the real recorder worker (acknowledged after commit) |
| latency | a tick's time from creation to a committed PostgreSQL row, and to the API price board |
| reconciliation | trades per second through the Checker, verified to find the 20 injected mistakes |

## Method
- Synthetic, deterministic ticks (same seed, same data). No live exchange is involved.
- A throwaway database (`deskpilot_bench`) and a uniquely named Redis stream; both removed afterwards.
- Every stage verifies itself (rows stored, stream length, injected breaks found) and fails
  loudly otherwise.
- Latency uses nearest-rank percentiles; the first 10% of samples are dropped as warm-up.
- Throughput stages can repeat (`--repeat`); the report gives the median and the range.
- Hardware, OS, Python, PostgreSQL and Redis versions are part of every result.

## How to read the latency numbers
A tick waits in the publisher's buffer until the batch is full (500 ticks) or the flush
interval passes. At about 500 ticks per second the flush interval is what a tick waits for, so
the default run measures 1.0 s and 0.05 s: the trade-off between latency and the number of writes.

## Limits
- Latency starts when OUR code creates the tick. Network time from the exchange is not included,
  and the dashboard adds up to one second (the SSE push interval).
- Feed, worker and API board run in ONE process on ONE machine: combined numbers are
  conservative; in production they are separate processes.
- Loopback network: Redis and PostgreSQL are on the same machine.
- Results depend on hardware and on what else is running. Compare runs on the same machine only.

## Results
Paste the `--markdown` output here with the date, and keep the JSON from `bench_runs/`.