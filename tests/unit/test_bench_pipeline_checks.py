import json

import pytest

from deskpilot.bench import (
    BenchReport,
    LatencyResult,
    StageResult,
    aggregate,
    bench_checker,
    bench_latency,
    bench_parse,
    format_markdown,
    format_text,
    report_to_dict,
    summarize,
)


def test_parsing_both_feeds_counts_every_message():
    results = bench_parse(500)
    assert [(r.name, r.count) for r in results] == [
        ("parse binance messages", 500),
        ("parse kraken messages", 500),
    ]
    assert all(r.seconds > 0 and r.rate > 0 for r in results)


def test_the_checker_benchmark_proves_all_injected_mistakes_are_found():
    result = bench_checker(200)
    assert result.name == "reconciliation"
    assert result.count >= 200
    assert result.rate > 0


@pytest.mark.parametrize(
    "arguments",
    [
        {"rate": 0, "duration": 5, "flush_interval": 1},
        {"rate": 100, "duration": 5, "flush_interval": 0},
        {"rate": 100, "duration": 5, "flush_interval": 1, "warmup": 1},
        {"rate": 5, "duration": 1, "flush_interval": 1},  # fewer than 10 ticks
    ],
)
async def test_nonsense_latency_settings_are_refused_before_anything_starts(arguments):
    with pytest.raises(ValueError):
        await bench_latency(None, None, "s", **arguments)


def make_report():
    summary = summarize([0.010, 0.020, 0.030])
    latency = LatencyResult(
        rate=500,
        duration=10,
        flush_interval=1.0,
        published=5000,
        dropped=0,
        delivered=5000,
        to_database=summary,
        to_board=summary,
        keeping_up=True,
    )
    stages = aggregate(
        [
            StageResult("publish to Redis", 1000, 0.5),
            StageResult("publish to Redis", 1000, 0.25),
            StageResult("publish to Redis", 1000, 1.0),
        ]
    )
    environment = {
        "python": "3.12",
        "system": "Linux",
        "cpu": "8 logical cores",
        "postgresql": "17.0",
        "redis": "7.2",
    }
    return BenchReport(environment, stages, [latency])


def test_the_median_and_range_of_repeated_runs():
    [stage] = make_report().stages
    assert (stage.runs, stage.count) == (3, 1000)
    assert (stage.median, stage.minimum, stage.maximum) == (2000, 1000, 4000)


def test_the_text_report_shows_environment_throughput_and_latency():
    text = format_text(make_report())
    assert "ENVIRONMENT" in text and "8 logical cores" in text
    assert "publish to Redis" in text and "2,000/s" in text and "[1,000/s to 4,000/s]" in text
    assert "flush 1s, 500/s, 5,000 ticks, dropped 0" in text
    assert "p99" in text and "30.0 ms" in text


def test_an_overloaded_run_says_so():
    report = make_report()
    overloaded = LatencyResult(**{**report.latency[0].__dict__, "keeping_up": False})
    assert "overloaded" in format_text(BenchReport({}, [], [overloaded]))


def test_the_markdown_report_has_tables_and_the_honest_caveat():
    text = format_markdown(make_report())
    assert "| Stage | Median | Range | Items per run | Runs |" in text
    assert "| publish to Redis | 2,000/s |" in text
    assert "| 1 s | 500/s | PostgreSQL | 20.0 ms |" in text
    assert "not exchange network latency" in text


def test_the_report_can_be_saved_as_json():
    data = report_to_dict(make_report())
    assert json.loads(json.dumps(data))["latency"][0]["to_database"]["p50"] == 0.02
