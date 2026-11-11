import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffPolicy:
    """How long to wait before reconnecting: grows each failure, up to a cap."""

    base: float = 1.0  # first wait, in seconds
    factor: float = 2.0  # each wait is this many times longer than the last
    cap: float = 30.0  # never wait longer than this
    jitter: float = 0.1  # random +/- 10%, so many clients don't retry in sync

    def __post_init__(self) -> None:
        if self.base <= 0:
            raise ValueError("base must be greater than 0")
        if self.factor < 1:
            raise ValueError("factor must be at least 1")
        if self.cap < self.base:
            raise ValueError("cap must be at least base")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter must be between 0 and 1")

    def delay(self, attempt: int, rand: Callable[[], float] = random.random) -> float:
        """Seconds to wait after the given failure number (0 = first failure)."""
        # min(attempt, 60) stops the power from growing absurdly large
        raw = min(self.cap, self.base * self.factor ** min(attempt, 60))
        spread = raw * self.jitter
        return max(0.0, raw + (rand() * 2 - 1) * spread)
