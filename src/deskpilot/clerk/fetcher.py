from typing import Protocol

from playwright.async_api import Browser, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from deskpilot.clerk.sources import SourceConfig

DEFAULT_USER_AGENT = "DeskPilotClerk/0.1 (announcement monitor; read-only)"


class FetchError(Exception):
    """The page could not be loaded."""


class Fetcher(Protocol):
    async def fetch(self, source: SourceConfig) -> str: ...


class PlaywrightFetcher:
    """Loads pages in a real headless browser, so JavaScript-built pages work.

    Use as: `async with PlaywrightFetcher() as fetcher: html = await fetcher.fetch(source)`.
    Each fetch gets a fresh browser context, so no cookies carry over between pages.
    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 30.0) -> None:
        self._user_agent = user_agent
        self._timeout_ms = int(timeout * 1000)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "PlaywrightFetcher":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = self._playwright = None

    async def fetch(self, source: SourceConfig) -> str:
        if self._browser is None:
            raise RuntimeError("use PlaywrightFetcher as `async with PlaywrightFetcher() as f`")
        context = await self._browser.new_context(user_agent=self._user_agent)
        try:
            page = await context.new_page()
            response = await page.goto(
                source.url, wait_until="domcontentloaded", timeout=self._timeout_ms
            )
            if response is not None and response.status >= 400:
                raise FetchError(f"{source.name}: HTTP {response.status}")
            if source.wait_for_selector:
                await page.wait_for_selector(source.wait_for_selector, timeout=self._timeout_ms)
            return await page.content()
        except PlaywrightError as error:  # includes timeouts
            reason = str(error).strip().splitlines()[0] if str(error).strip() else "unknown"
            raise FetchError(f"{source.name}: {type(error).__name__}: {reason}") from None
        finally:
            await context.close()
