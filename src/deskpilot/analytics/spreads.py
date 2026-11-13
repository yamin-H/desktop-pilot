from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from deskpilot.models import Exchange, PriceTick


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Spread:
    """The gap between the most expensive and the cheapest exchange for one coin pair."""

    symbol: str
    high: PriceTick
    low: PriceTick

    @property
    def amount(self) -> Decimal:
        """How much more expensive the high exchange is, in the quote currency."""
        return self.high.price - self.low.price

    @property
    def percent(self) -> Decimal:
        """The gap as a percentage of the cheaper price."""
        return self.amount / self.low.price * 100


class PriceBoard:
    """Remembers the latest price per exchange and coin pair, and measures the gaps.

    `on_tick` can be handed straight to a feed as its tick handler.
    """

    def __init__(
        self,
        max_age: float = 30.0,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_age <= 0:
            raise ValueError("max_age must be greater than 0")
        self._max_age = max_age
        self._clock = clock  # replaced in tests, so time can be controlled
        self._latest: dict[tuple[Exchange, str], PriceTick] = {}

    async def on_tick(self, tick: PriceTick) -> None:
        key = (tick.exchange, tick.symbol)
        current = self._latest.get(key)
        # A late, older message must never replace a newer price.
        if current is None or tick.exchange_time >= current.exchange_time:
            self._latest[key] = tick

    def latest(self, exchange: Exchange, symbol: str) -> PriceTick | None:
        return self._latest.get((exchange, symbol))

    def spreads(self) -> list[Spread]:
        """One Spread per coin pair that has fresh prices from at least two exchanges."""
        now = self._clock()
        fresh: dict[str, list[PriceTick]] = {}
        for tick in self._latest.values():
            if (now - tick.received_time).total_seconds() <= self._max_age:
                fresh.setdefault(tick.symbol, []).append(tick)

        result = []
        for symbol in sorted(fresh):
            ticks = fresh[symbol]
            if len(ticks) < 2:
                continue
            # Sorting (instead of min/max) guarantees high and low are different
            # exchanges even when two prices are exactly equal.
            ordered = sorted(ticks, key=lambda t: (t.price, t.exchange.value))
            result.append(Spread(symbol=symbol, high=ordered[-1], low=ordered[0]))
        return result

    @property
    def max_age(self) -> float:
        return self._max_age

    def now(self) -> datetime:
        return self._clock()

    def ticks(self) -> list[PriceTick]:
        """Every stored tick (fresh or not): one per exchange and coin pair."""
        return list(self._latest.values())
