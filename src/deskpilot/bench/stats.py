import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile: the smallest value that at least p% of the values do not exceed.

    `sorted_values` must be sorted. Exact fractions are used for the rank, so floating-point
    noise (0.07 * 100 = 7.000000000000001) can never move a result.
    """
    if not sorted_values:
        raise ValueError("no values")
    if not 0 < p <= 100:
        raise ValueError("p must be above 0 and at most 100")
    rank = math.ceil(Fraction(str(p)) * len(sorted_values) / 100)
    return sorted_values[min(max(rank, 1), len(sorted_values)) - 1]


@dataclass(frozen=True)
class LatencySummary:
    count: int
    minimum: float  # all times in seconds
    mean: float
    p50: float
    p95: float
    p99: float
    maximum: float


def summarize(values: Iterable[float]) -> LatencySummary:
    data = sorted(values)
    if not data:
        raise ValueError("no values to summarize")
    return LatencySummary(
        count=len(data),
        minimum=data[0],
        mean=math.fsum(data) / len(data),
        p50=percentile(data, 50),
        p95=percentile(data, 95),
        p99=percentile(data, 99),
        maximum=data[-1],
    )


def per_second(count: int, seconds: float) -> float:
    if seconds <= 0:
        raise ValueError("seconds must be above 0")
    return count / seconds


def format_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def format_rate(rate: float) -> str:
    return f"{rate:,.0f}/s"