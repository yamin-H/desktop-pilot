"""Measure the pipeline and print numbers you can put in a README.

Usage:
  uv run python scripts/benchmark.py                  # the full run (a few minutes)
  uv run python scripts/benchmark.py --quick          # a fast smoke test
  uv run python scripts/benchmark.py --repeat 3 --markdown
  uv run python scripts/benchmark.py --only parse checker

Needs PostgreSQL and Redis (make db-up). A throwaway database and stream are created and
removed, so your data is never touched. Close other heavy programs first, and run it three
times: numbers vary between runs and machines.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from redis import exceptions as redis_errors

from deskpilot.bench import (
    BenchmarkError,
    BenchReport,
    LatencyResult,
    StageResult,
    aggregate,
    bench_checker,
    bench_consume,
    bench_latency,
    bench_parse,
    bench_publish,
    describe_environment,
    format_markdown,
    format_rate,
    format_text,
    make_ticks,
    report_to_dict,
    temporary_database,
    temporary_stream,
)
from deskpilot.bus import make_redis
from deskpilot.config import get_settings

STAGES = ("parse", "throughput", "latency", "checker")
OUTPUT = Path(__file__).resolve().parent.parent / "bench_runs"


def show(result: StageResult) -> None:
    print(
        f"  {result.name:<26}{format_rate(result.rate):>14}   ({result.count:,} items in {result.seconds:.2f}s)",
        flush=True,
    )


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    redis = make_redis(settings.redis_url)
    try:
        await redis.ping()
    except (OSError, redis_errors.RedisError) as error:
        print(f"Cannot reach Redis ({error}). Run: make db-up")
        await redis.aclose()
        return 2

    sizes = dict(
        parse=args.parse,
        ticks=args.ticks,
        rate=args.rate,
        duration=args.duration,
        checker=args.checker,
    )
    if args.quick:
        sizes = dict(parse=20_000, ticks=10_000, rate=500, duration=5.0, checker=2_000)
    stages = set(args.only or STAGES)

    results: list[StageResult] = []
    latencies: list[LatencyResult] = []
    try:
        async with temporary_database(settings.database_url) as pool:
            environment = await describe_environment(redis, pool)
            for run in range(1, args.repeat + 1):
                print(f"run {run}/{args.repeat}", flush=True)
                if "parse" in stages:
                    for result in bench_parse(sizes["parse"], seed=run):
                        show(result)
                        results.append(result)
                if "throughput" in stages:
                    async with temporary_stream(redis) as stream:
                        ticks = make_ticks(sizes["ticks"], seed=run)
                        for result in (
                            await bench_publish(redis, stream, ticks),
                            await bench_consume(redis, pool, stream, len(ticks)),
                        ):
                            show(result)
                            results.append(result)
                if "checker" in stages:
                    result = bench_checker(sizes["checker"])
                    show(result)
                    results.append(result)

            if "latency" in stages:
                for flush in args.flush_intervals:
                    print(
                        f"latency: {sizes['rate']}/s for {sizes['duration']:g}s, flush {flush:g}s ...",
                        flush=True,
                    )
                    async with temporary_stream(redis) as stream:
                        latencies.append(
                            await bench_latency(
                                redis,
                                pool,
                                stream,
                                rate=sizes["rate"],
                                duration=sizes["duration"],
                                flush_interval=flush,
                            )
                        )
    except BenchmarkError as error:
        print(f"\nBENCHMARK FAILED: {error}")
        return 1
    finally:
        await redis.aclose()

    report = BenchReport(environment, aggregate(results), latencies)
    print("\n" + format_text(report))
    if args.markdown:
        print("\n" + format_markdown(report))

    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
    print(f"\nsaved: {path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark the DeskPilot pipeline.")
    parser.add_argument("--parse", type=int, default=200_000, help="messages per parse run")
    parser.add_argument("--ticks", type=int, default=100_000, help="ticks per throughput run")
    parser.add_argument(
        "--rate", type=int, default=500, help="ticks per second for the latency run"
    )
    parser.add_argument("--duration", type=float, default=20.0, help="seconds of the latency run")
    parser.add_argument("--flush-intervals", type=float, nargs="+", default=[1.0, 0.05])
    parser.add_argument("--checker", type=int, default=20_000, help="trades for the Checker run")
    parser.add_argument(
        "--repeat", type=int, default=1, help="repeat parse, throughput and Checker runs"
    )
    parser.add_argument("--only", nargs="+", choices=STAGES, help="run only these stages")
    parser.add_argument("--quick", action="store_true", help="small sizes, for a smoke test")
    parser.add_argument("--markdown", action="store_true", help="also print README-ready tables")
    arguments = parser.parse_args()
    if arguments.repeat < 1:
        parser.error("--repeat must be at least 1")
    sys.exit(asyncio.run(main(arguments)))
