import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Allows at most `max_calls` per `per_seconds` (a sliding window)."""

    def __init__(
        self, max_calls: int, per_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_calls < 1 or per_seconds <= 0:
            raise ValueError("max_calls must be at least 1 and per_seconds above 0")
        self._max_calls = max_calls
        self._per_seconds = per_seconds
        self._clock = clock
        self._calls: deque[float] = deque()

    def try_acquire(self) -> float | None:
        """None if allowed (and counted). Otherwise the seconds until a slot frees up."""
        now = self._clock()
        while self._calls and now - self._calls[0] >= self._per_seconds:
            self._calls.popleft()
        if len(self._calls) >= self._max_calls:
            return self._per_seconds - (now - self._calls[0])
        self._calls.append(now)
        return None
