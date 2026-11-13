import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deskpilot.clerk.fetcher import FetchError, PlaywrightFetcher
from deskpilot.clerk.sources import SourceConfig

STATIC = '<ul><li class="item"><a href="https://x.test/1">Static item</a></li></ul>'
JS = """<ul id="list"></ul><script>
setTimeout(() => { document.getElementById('list').innerHTML =
  '<li class="item"><a href="https://x.test/2">Late item</a></li>'; }, 300);
</script>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pages = {"/static": (200, STATIC), "/js": (200, JS)}
        status, body = pages.get(self.path, (404, "not found"))
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def chromium_ready():
    pytest.importorskip("playwright")

    async def probe():
        async with PlaywrightFetcher():
            pass

    try:
        asyncio.run(probe())
    except Exception as error:
        pytest.skip(
            f"Chromium is not available ({type(error).__name__}). Run: uv run playwright install chromium"
        )


def source(url, **extra):
    return SourceConfig(name="t", url=url, item_selector="li.item", **extra)


async def test_a_page_is_loaded_and_returned_as_html(chromium_ready, base_url):
    async with PlaywrightFetcher() as fetcher:
        assert "Static item" in await fetcher.fetch(source(f"{base_url}/static"))


async def test_a_page_built_by_javascript_can_be_waited_for(chromium_ready, base_url):
    async with PlaywrightFetcher() as fetcher:
        html = await fetcher.fetch(source(f"{base_url}/js", wait_for_selector="li.item"))
    assert "Late item" in html


async def test_an_error_status_is_a_fetch_error(chromium_ready, base_url):
    async with PlaywrightFetcher() as fetcher:
        with pytest.raises(FetchError, match="HTTP 404"):
            await fetcher.fetch(source(f"{base_url}/missing"))


async def test_an_unreachable_site_is_a_fetch_error(chromium_ready):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # a port nobody listens on
    async with PlaywrightFetcher(timeout=5) as fetcher:
        with pytest.raises(FetchError):
            await fetcher.fetch(source(f"http://127.0.0.1:{port}/"))


async def test_a_selector_that_never_appears_times_out_as_a_fetch_error(chromium_ready, base_url):
    async with PlaywrightFetcher(timeout=1) as fetcher:
        with pytest.raises(FetchError, match="Timeout"):
            await fetcher.fetch(source(f"{base_url}/static", wait_for_selector="div.never"))


async def test_using_the_fetcher_without_starting_it_is_a_programming_error():
    with pytest.raises(RuntimeError, match="async with"):
        await PlaywrightFetcher().fetch(source("https://x.test/"))
