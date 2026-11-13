import json

import httpx
import pytest

from deskpilot.clerk.alerts import (
    AlertError,
    ConsoleAlerter,
    MultiAlerter,
    SlackAlerter,
    TelegramAlerter,
    build_alerter,
    format_alert,
)
from deskpilot.clerk.models import Announcement, Category, Classified
from deskpilot.config import Settings


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def item(title="Scheduled maintenance", assets=("BTC",)):
    announcement = Announcement("demo", "https://x.test/1", title, "https://x.test/1")
    return Classified(announcement, Category.MAINTENANCE, assets, True)


def test_the_alert_text_has_category_source_title_assets_and_link():
    assert format_alert(item()) == (
        "[MAINTENANCE] demo: Scheduled maintenance\nMentions: BTC\nhttps://x.test/1"
    )
    assert "Mentions" not in format_alert(item(assets=()))


def test_the_alert_cleans_control_characters_and_cuts_long_titles():
    text = format_alert(item(title="Bad\r\n\x07title " + "w" * 500))
    assert "\x07" not in text
    assert text.splitlines()[0].startswith("[MAINTENANCE] demo: Bad title ")
    assert len(text.splitlines()[0]) <= len("[MAINTENANCE] demo: ") + 200


async def test_telegram_sends_plain_text_without_a_link_preview():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await TelegramAlerter("123:SECRET", "42", client(handler)).send("hello")
    assert seen["path"] == "/bot123:SECRET/sendMessage"
    assert seen["body"] == {"chat_id": "42", "text": "hello", "disable_web_page_preview": True}


async def test_telegram_messages_are_cut_to_the_size_limit():
    seen = {}

    def handler(request):
        seen["text"] = json.loads(request.content)["text"]
        return httpx.Response(200, json={"ok": True})

    await TelegramAlerter("t", "c", client(handler)).send("x" * 9000)
    assert len(seen["text"]) == 4000


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"ok": False}),
        httpx.Response(200, json={"ok": False}),
        httpx.Response(200, text="oops"),
    ],
)
async def test_a_refusal_is_an_alert_error_that_hides_the_token(response):
    alerter = TelegramAlerter("123:SECRET", "42", client(lambda request: response))
    with pytest.raises(AlertError) as error:
        await alerter.send("hello")
    assert "SECRET" not in str(error.value)


async def test_a_network_failure_is_an_alert_error_that_hides_the_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(AlertError) as error:
        await TelegramAlerter("123:SECRET", "42", client(handler)).send("hello")
    assert "SECRET" not in str(error.value)
    assert "ConnectError" in str(error.value)


async def test_slack_escapes_markup_and_hides_the_webhook():
    seen = {}

    def handler(request):
        seen["text"] = json.loads(request.content)["text"]
        return httpx.Response(200, text="ok")

    await SlackAlerter("https://hooks.test/SECRET", client(handler)).send("a <b> & c")
    assert seen["text"] == "a &lt;b&gt; &amp; c"

    refused = SlackAlerter("https://hooks.test/SECRET", client(lambda r: httpx.Response(404)))
    with pytest.raises(AlertError) as error:
        await refused.send("x")
    assert "SECRET" not in str(error.value)
    assert "404" in str(error.value)


class Recording:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, message):
        if self.fail:
            raise AlertError("down")
        self.sent.append(message)


async def test_every_channel_is_tried_and_one_failure_is_tolerated():
    good, bad = Recording(), Recording(fail=True)
    await MultiAlerter([bad, good]).send("hi")
    assert good.sent == ["hi"]


async def test_it_fails_only_when_every_channel_fails():
    with pytest.raises(AlertError, match="down; down"):
        await MultiAlerter([Recording(fail=True), Recording(fail=True)]).send("hi")


def test_at_least_one_channel_is_required():
    with pytest.raises(ValueError):
        MultiAlerter([])


def settings(**fields):
    return Settings(_env_file=None, **fields)


def test_the_alerter_is_built_from_the_settings():
    assert isinstance(build_alerter(settings()), ConsoleAlerter)
    assert isinstance(
        build_alerter(settings(telegram_bot_token="t", telegram_chat_id="c")), TelegramAlerter
    )
    assert isinstance(build_alerter(settings(slack_webhook_url="https://h")), SlackAlerter)
    both = settings(telegram_bot_token="t", telegram_chat_id="c", slack_webhook_url="https://h")
    assert isinstance(build_alerter(both), MultiAlerter)


@pytest.mark.parametrize("fields", [{"telegram_bot_token": "t"}, {"telegram_chat_id": "c"}])
def test_half_a_telegram_setup_is_refused(fields):
    with pytest.raises(ValueError, match="both"):
        build_alerter(settings(**fields))
