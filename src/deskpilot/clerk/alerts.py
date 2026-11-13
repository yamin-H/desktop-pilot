import logging
import re
from collections.abc import Sequence
from typing import Protocol

import httpx

from deskpilot.clerk.models import Classified
from deskpilot.config import Settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class AlertError(Exception):
    """An alert could not be delivered. The message never contains a token or webhook URL."""


class Alerter(Protocol):
    async def send(self, message: str) -> None: ...


def _clean(text: str) -> str:
    return _CONTROL.sub(" ", text).strip()


def format_alert(item: Classified) -> str:
    """Plain text. The title comes from a website, so it is cleaned and shortened."""
    announcement = item.announcement
    lines = [
        f"[{item.category.value.upper()}] {announcement.source}: {_clean(announcement.title)[:200]}"
    ]
    if item.assets:
        lines.append("Mentions: " + ", ".join(item.assets))
    lines.append(announcement.url)
    return "\n".join(lines)


class ConsoleAlerter:
    async def send(self, message: str) -> None:
        print(f"ALERT\n{message}\n", flush=True)


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"  # contains the secret
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def send(self, message: str) -> None:
        payload = {
            "chat_id": self._chat_id,
            "text": message[:TELEGRAM_LIMIT],
            "disable_web_page_preview": True,
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.HTTPError as error:  # not included in the message: it may show the URL
            raise AlertError(f"could not reach Telegram ({type(error).__name__})") from None
        if response.status_code != 200:
            raise AlertError(f"Telegram refused the message (HTTP {response.status_code})")
        try:
            accepted = response.json().get("ok") is True
        except ValueError:
            accepted = False
        if not accepted:
            raise AlertError("Telegram did not accept the message")


class SlackAlerter:
    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = webhook_url  # a secret
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def send(self, message: str) -> None:
        text = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            response = await self._client.post(self._url, json={"text": text})
        except httpx.HTTPError as error:
            raise AlertError(f"could not reach Slack ({type(error).__name__})") from None
        if response.status_code != 200:
            raise AlertError(f"Slack refused the message (HTTP {response.status_code})")


class MultiAlerter:
    """Sends to every channel. Fails only if ALL of them fail."""

    def __init__(self, alerters: Sequence[Alerter]) -> None:
        if not alerters:
            raise ValueError("at least one alerter is required")
        self._alerters = list(alerters)

    async def send(self, message: str) -> None:
        errors: list[str] = []
        for alerter in self._alerters:
            try:
                await alerter.send(message)
            except AlertError as error:
                errors.append(str(error))
        if len(errors) == len(self._alerters):
            raise AlertError("; ".join(errors))
        for error in errors:
            logger.warning("one alert channel failed: %s", error)


def build_alerter(settings: Settings, client: httpx.AsyncClient | None = None) -> Alerter:
    """Telegram and/or Slack if configured, otherwise print to the console."""
    if bool(settings.telegram_bot_token) != bool(settings.telegram_chat_id):
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set, or neither")
    alerters: list[Alerter] = []
    if settings.telegram_bot_token:
        alerters.append(
            TelegramAlerter(settings.telegram_bot_token, settings.telegram_chat_id, client)
        )
    if settings.slack_webhook_url:
        alerters.append(SlackAlerter(settings.slack_webhook_url, client))
    if not alerters:
        return ConsoleAlerter()
    return alerters[0] if len(alerters) == 1 else MultiAlerter(alerters)
