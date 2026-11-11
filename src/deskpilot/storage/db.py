import asyncpg


async def create_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """A pool of reusable database connections."""
    return await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,  # a query stuck for 30s is a problem, not something to wait for
    )
