import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from deskpilot.bench.pipeline import LatencyResult, StageResult
from deskpilot.bench.stats import format_ms, format_rate


@dataclass(frozen=True)
class Aggregate:
    name: str
    runs: int
    count: int
    median: float  # items per second
    minimum: float
    maximum: float


@dataclass(frozen=True)
class BenchReport:
    environment: dict[str, str]
    stages: list[Aggregate]
    latency: list[LatencyResult]


def aggregate(results: Sequence[StageResult]) -> list[Aggregate]:
    """One line per stage: the median speed over all runs, and the range."""
    grouped: dict[str, list[StageResult]] = {}
    for result in results:
        grouped.setdefault(result.name, []).append(result)
    return [
        Aggregate(
            name=name,
            runs=len(runs),
            count=runs[0].count,
            median=statistics.median(run.rate for run in runs),
            minimum=min(run.rate for run in runs),
            maximum=max(run.rate for run in runs),
        )
        for name, runs in grouped.items()
    ]


def format_text(report: BenchReport) -> str:
    lines = ["ENVIRONMENT"]
    lines += [f"  {key:<12}{value}" for key, value in report.environment.items()]
    if report.stages:
        lines += ["", "THROUGHPUT (median of the runs, with the range)"]
        for s in report.stages:
            spread = (
                f"  [{format_rate(s.minimum)} to {format_rate(s.maximum)}]" if s.runs > 1 else ""
            )
            lines.append(
                f"  {s.name:<26}{format_rate(s.median):>14}{spread}   ({s.count:,} items, {s.runs} run(s))"
            )
    if report.latency:
        lines += [
            "",
            "LATENCY (tick created -> committed in PostgreSQL / applied to the API board)",
        ]
        for r in report.latency:
            note = "" if r.keeping_up else "  (producer could not keep up: overloaded)"
            lines.append(
                f"  flush {r.flush_interval:g}s, {r.rate}/s, {r.delivered:,} ticks, dropped {r.dropped}{note}"
            )
            for label, s in (("database", r.to_database), ("board", r.to_board)):
                lines.append(
                    f"    {label:<9} p50 {format_ms(s.p50):>10}  p95 {format_ms(s.p95):>10}  "
                    f"p99 {format_ms(s.p99):>10}  max {format_ms(s.maximum):>10}"
                )
    return "\n".join(lines)


def format_markdown(report: BenchReport) -> str:
    env = report.environment
    lines = [
        f"Measured on {env.get('system')}, {env.get('cpu')}, Python {env.get('python')}, "
        f"PostgreSQL {env.get('postgresql')}, Redis {env.get('redis')}. "
        "Synthetic ticks, one process, loopback network: internal pipeline numbers, "
        "not exchange network latency.",
        "",
    ]
    if report.stages:
        lines += ["| Stage | Median | Range | Items per run | Runs |", "|---|---|---|---|---|"]
        for s in report.stages:
            lines.append(
                f"| {s.name} | {format_rate(s.median)} | {format_rate(s.minimum)} to "
                f"{format_rate(s.maximum)} | {s.count:,} | {s.runs} |"
            )
        lines.append("")
    if report.latency:
        lines += [
            "| Flush interval | Rate | Target | p50 | p95 | p99 | max |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in report.latency:
            for label, s in (("PostgreSQL", r.to_database), ("API board", r.to_board)):
                lines.append(
                    f"| {r.flush_interval:g} s | {r.rate}/s | {label} | {format_ms(s.p50)} | "
                    f"{format_ms(s.p95)} | {format_ms(s.p99)} | {format_ms(s.maximum)} |"
                )
    return "\n".join(lines)


def report_to_dict(report: BenchReport) -> dict:
    return asdict(report)
