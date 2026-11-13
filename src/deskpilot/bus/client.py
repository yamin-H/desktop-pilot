from redis import exceptions as redis_errors
from redis.asyncio import Redis

# Connection-type trouble that is worth retrying. Other Redis errors mean a bug.
REDIS_RETRYABLE: tuple[type[BaseException], ...] = (
    redis_errors.ConnectionError,
    redis_errors.TimeoutError,
    redis_errors.BusyLoadingError,
)


def make_redis(url: str) -> Redis:
    """A Redis client that returns text. Timeouts are longer than our 1 second blocking reads."""
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
