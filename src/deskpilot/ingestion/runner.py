import asyncio
from collections.abc import Sequence
from typing import Protocol


class Runnable(Protocol):
    async def run(self) -> None: ...


async def run_feeds(feeds: Sequence[Runnable]) -> None:
    """Run all feeds at the same time, until cancelled.

    Connection problems are handled inside each feed. If one feed hits a real bug,
    everything is stopped and the error is raised, instead of leaving the system
    half-working in silence.
    """
    if not feeds:
        raise ValueError("at least one feed is required")
    async with asyncio.TaskGroup() as group:
        for feed in feeds:
            group.create_task(feed.run())
