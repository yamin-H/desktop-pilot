import asyncpg

from deskpilot.bench import (
    bench_consume,
    bench_latency,
    bench_publish,
    describe_environment,
    make_ticks,
    temporary_database,
    temporary_stream,
)
from deskpilot.config import get_settings


async def test_publishing_then_consuming_moves_every_tick_exactly_once(pool, stream_env):
    ticks = make_ticks(1500)
    published = await bench_publish(stream_env.redis, stream_env.stream, ticks)
    assert (published.count, published.seconds > 0) == (1500, True)

    consumed = await bench_consume(stream_env.redis, pool, stream_env.stream, 1500)
    assert consumed.count == 1500
    assert await pool.fetchval("SELECT count(*) FROM prices") == 1500
    assert (await stream_env.redis.xpending(stream_env.stream, "bench"))["pending"] == 0


async def test_a_latency_run_delivers_everything_to_the_database_and_the_board(pool, stream_env):
    result = await bench_latency(
        stream_env.redis, pool, stream_env.stream, rate=300, duration=1.0, flush_interval=0.02
    )
    assert (result.published, result.dropped, result.delivered) == (300, 0, 300)
    assert await pool.fetchval("SELECT count(*) FROM prices") == 300

    for summary in (result.to_database, result.to_board):
        assert summary.count == 270  # 10% warm-up dropped
        assert 0 <= summary.p50 <= summary.p99 <= summary.maximum
        assert summary.p99 < 10  # generous: only catches a broken pipeline, not slow hardware


async def test_the_temporary_database_exists_only_inside_the_block(test_database_url):
    admin_url = get_settings().database_url
    async with temporary_database(admin_url, name="deskpilot_bench_test") as pool:
        assert await pool.fetchval("SELECT current_database()") == "deskpilot_bench_test"
        assert await pool.fetchval("SELECT count(*) FROM schema_migrations") >= 6

    admin = await asyncpg.connect(admin_url)
    try:
        query = "SELECT count(*) FROM pg_database WHERE datname = 'deskpilot_bench_test'"
        assert await admin.fetchval(query) == 0
    finally:
        await admin.close()


async def test_a_temporary_stream_is_deleted_afterwards(stream_env):
    async with temporary_stream(stream_env.redis) as stream:
        await stream_env.redis.xadd(stream, {"a": "1"})
        assert await stream_env.redis.exists(stream) == 1
    assert await stream_env.redis.exists(stream) == 0


async def test_the_environment_description_names_every_component(pool, stream_env):
    environment = await describe_environment(stream_env.redis, pool)
    assert set(environment) == {"python", "system", "cpu", "postgresql", "redis"}
    assert all(value and value != "?" for value in environment.values())
