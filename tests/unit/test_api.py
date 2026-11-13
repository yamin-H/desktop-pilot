import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import openai
import pytest
from redis import exceptions as redis_errors

from deskpilot.agent import Agent, StaticData, ToolContext, build_default_registry
from deskpilot.agent.tools import Tool, ToolRegistry
from deskpilot.agent.tools.ledger import PositionArgs
from deskpilot.analytics import PriceBoard
from deskpilot.api.app import ApiState, create_app
from deskpilot.api.limits import RateLimiter
from deskpilot.clerk.models import Announcement, Category, Classified
from deskpilot.config import Settings
from deskpilot.models import PriceTick

CLEAN = (
    "trade_id,symbol,side,quantity,price,fee,fee_asset,executed_at\n"
    "PAPER-0001,BTC/USDT,buy,0.50,60000,0.0005,BTC,2026-11-10T10:00:00Z\n"
    "PAPER-0002,BTC/USDT,buy,0.25,61000,15.25,USDT,2026-11-10T11:30:00Z\n"
    "PAPER-0003,BTC/USDT,sell,0.40,62500,25.00,USDT,2026-11-10T14:15:00Z\n"
)

ANNOUNCEMENTS = [
    Classified(
        Announcement(
            "demo",
            "https://x.test/1",
            "Scheduled maintenance",
            "https://x.test/1",
            datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
        ),
        Category.MAINTENANCE,
        ("BTC",),
        True,
    ),
    Classified(
        Announcement("demo", "https://x.test/2", "Weekly update", "https://x.test/2"),
        Category.OTHER,
        (),
        False,
    ),
]


class FakeAnnouncements:
    def __init__(self, items):
        self.items, self.calls = items, []

    async def list_recent(self, limit=20, *, important_only=False):
        self.calls.append((limit, important_only))
        return [i for i in self.items if i.important or not important_only][:limit]


class FakeClient:
    def __init__(self, replies):
        self._replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def say(text):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def use_tool(call_id, name):
    call = SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments="{}")
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))]
    )


@pytest.fixture
async def make_client(paper_trades, paper_prices, now, tmp_path):
    opened = []

    def build(**settings_fields):
        context = ToolContext(
            data=StaticData(paper_trades, paper_prices),
            statements_dir=tmp_path / "statements",
            clock=lambda: now,
        )
        state = ApiState(
            settings=Settings(_env_file=None, **settings_fields),
            board=PriceBoard(max_age=30, clock=lambda: now),
            context=context,
            registry=build_default_registry(),
            announcements=FakeAnnouncements(ANNOUNCEMENTS),
            stream_interval=0,
            stream_limit=2,
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(state)), base_url="http://test"
        )
        opened.append(client)
        return client, state

    yield build
    for client in opened:
        await client.aclose()


# --- health and access ----------------------------------------------------------------------


async def test_health_is_ok_and_needs_no_token(make_client):
    client, _ = make_client(api_token="secret")
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_reports_an_unreachable_database_with_503(make_client):
    client, state = make_client()

    async def broken(query):
        raise OSError("down")

    state.pool = SimpleNamespace(fetchval=broken)
    response = await client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


async def test_health_reports_a_stopped_market_poller_with_503(make_client):
    client, state = make_client()
    state.poller = asyncio.create_task(asyncio.sleep(0))
    await state.poller
    response = await client.get("/api/health")
    assert (response.status_code, response.json()["market_poller"]) == (503, "stopped")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({"authorization": "Bearer wrong"}, 401),
        ({"authorization": "Basic secret"}, 401),
        ({"authorization": "Bearer secret"}, 200),
        ({"authorization": "bearer secret"}, 200),
    ],
)
async def test_a_configured_token_is_required(make_client, headers, status):
    client, _ = make_client(api_token="secret")
    response = await client.get("/api/positions", headers=headers)
    assert response.status_code == status
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


async def test_without_a_configured_token_nothing_is_required(make_client):
    client, _ = make_client()
    assert (await client.get("/api/positions")).status_code == 200


async def test_the_config_says_whether_chat_is_available(make_client):
    client, state = make_client()
    assert (await client.get("/api/config")).json() == {"chat_enabled": False}
    state.settings = Settings(_env_file=None, api_enable_chat=True)
    assert (await client.get("/api/config")).json() == {"chat_enabled": False}  # no agent yet
    state.agent = object()
    assert (await client.get("/api/config")).json() == {"chat_enabled": True}


# --- market ---------------------------------------------------------------------------------


async def test_the_market_endpoint_serves_the_board(make_client, now):
    client, state = make_client()
    for exchange, price in (("binance", "100.50"), ("kraken", "100.00")):
        await state.board.on_tick(
            PriceTick(
                exchange=exchange,
                symbol="BTC/USDT",
                price=price,
                exchange_time=now,
                received_time=now,
            )
        )
    data = (await client.get("/api/market")).json()
    assert data["spreads"][0]["amount"] == "0.5"
    assert [p["exchange"] for p in data["prices"]] == ["binance", "kraken"]


async def test_the_live_stream_sends_events(make_client):
    client, _ = make_client()
    response = await client.get("/api/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers["cache-control"]
    assert response.text.count("event: market") == 2


async def test_too_many_live_connections_are_refused(make_client):
    client, state = make_client()
    state.max_streams = 0
    assert (await client.get("/api/stream")).status_code == 503


# --- ledger endpoints (same numbers as the assistant) ---------------------------------------


async def test_positions(make_client):
    client, _ = make_client()
    data = (await client.get("/api/positions")).json()
    assert data["count"] == 2
    assert data["positions"][0]["quantity"] == "0.3495"
    kraken = (await client.get("/api/positions", params={"exchange": "kraken"})).json()
    assert [p["symbol"] for p in kraken["positions"]] == ["ETH/USDT"]


async def test_pnl_totals_match_the_hand_calculated_numbers(make_client):
    client, _ = make_client()
    data = (await client.get("/api/pnl")).json()
    assert data["totals"] == [
        {
            "quote_currency": "USDT",
            "realized_pnl": "1005.23",
            "unrealized_pnl": "1051.82",
            "total_pnl": "2057.05",
            "missing_prices": [],
        }
    ]


async def test_realized_profit_for_a_period(make_client):
    client, _ = make_client()
    response = await client.get(
        "/api/realized", params={"start": "2026-11-10", "end": "2026-11-11"}
    )
    assert response.json()["totals"] == [
        {"quote_currency": "USDT", "realized_pnl": "1005.23", "sales": 2}
    ]


async def test_trades_are_limited_and_the_limit_is_validated(make_client):
    client, _ = make_client()
    data = (await client.get("/api/trades", params={"limit": 2})).json()
    assert (data["total_matching"], data["shown"]) == (5, 2)
    assert (await client.get("/api/trades", params={"limit": 0})).status_code == 422


async def test_a_problem_the_user_can_fix_is_a_422_with_the_reason(make_client):
    client, _ = make_client()
    response = await client.get("/api/positions", params={"symbol": "BTCUSDT"})
    assert response.status_code == 422
    assert "BTC/USDT" in response.json()["detail"]
    assert (await client.get("/api/positions", params={"exchange": "ftx"})).status_code == 422


async def test_a_bug_is_a_500_without_details(make_client):
    client, state = make_client()

    async def crash(context, args):
        raise RuntimeError("secret detail")

    state.registry = ToolRegistry([Tool("get_pnl", "x", PositionArgs, crash)])
    response = await client.get("/api/pnl")
    assert (response.status_code, response.json()) == (500, {"detail": "internal error"})


async def test_reconciliation(make_client, tmp_path):
    client, _ = make_client()
    (tmp_path / "statements").mkdir()
    (tmp_path / "statements" / "clean.csv").write_text(CLEAN, encoding="utf-8")
    params = {
        "exchange": "binance",
        "statement": "clean.csv",
        "start": "2026-11-10",
        "end": "2026-11-11",
    }
    assert (await client.get("/api/recon", params=params)).json()["is_clean"] is True
    escape = await client.get("/api/recon", params={**params, "statement": "../clean.csv"})
    assert escape.status_code == 422
    assert "not a valid statement file name" in escape.json()["detail"]


async def test_announcements(make_client):
    client, state = make_client()
    data = (await client.get("/api/announcements")).json()
    assert data["count"] == 2
    assert data["announcements"][0] == {
        "source": "demo",
        "title": "Scheduled maintenance",
        "url": "https://x.test/1",
        "category": "maintenance",
        "assets": ["BTC"],
        "important": True,
        "time": "2026-11-12T08:00:00Z",
    }
    assert data["announcements"][1]["time"] is None
    important = (
        await client.get("/api/announcements", params={"important_only": "true", "limit": 5})
    ).json()
    assert important["count"] == 1
    assert state.announcements.calls[-1] == (5, True)
    assert (await client.get("/api/announcements", params={"limit": 51})).status_code == 422


# --- chat -----------------------------------------------------------------------------------


def enable_chat(make_client, replies, **settings):
    client, state = make_client(api_enable_chat=True, **settings)
    state.agent = Agent(FakeClient(replies), "test-model", state.registry, state.context)
    return client, state


async def test_chat_is_off_by_default(make_client):
    client, _ = make_client()
    response = await client.post("/api/chat", json={"question": "What do we hold?"})
    assert response.status_code == 403


async def test_chat_without_a_configured_assistant_is_a_503(make_client):
    client, _ = make_client(api_enable_chat=True)
    assert (
        await client.post("/api/chat", json={"question": "What do we hold?"})
    ).status_code == 503


async def test_a_question_gets_an_answer_and_the_tools_used(make_client):
    client, _ = enable_chat(
        make_client, [use_tool("1", "get_positions"), say("We hold 0.3495 BTC.")]
    )
    response = await client.post("/api/chat", json={"question": "What do we hold?"})
    assert response.status_code == 200
    assert response.json() == {
        "answer": "We hold 0.3495 BTC.",
        "tools": [{"name": "get_positions", "arguments": "{}", "ok": True}],
    }


@pytest.mark.parametrize("question", ["hi", "x" * 501])
async def test_a_question_must_have_a_sensible_length(make_client, question):
    client, _ = enable_chat(make_client, [say("ok")])
    assert (await client.post("/api/chat", json={"question": question})).status_code == 422


async def test_too_many_questions_are_refused_with_retry_after(make_client):
    client, state = enable_chat(make_client, [say("one"), say("two")])
    state.chat_limiter = RateLimiter(1, 60)
    assert (await client.post("/api/chat", json={"question": "first question"})).status_code == 200
    second = await client.post("/api/chat", json={"question": "second question"})
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1


async def test_health_says_redis_is_off_when_it_is_not_used(make_client):
    client, _ = make_client()
    body = (await client.get("/api/health")).json()
    assert (body["redis"], body["market_source"]) == ("off", "database")


async def test_health_shows_redis_when_it_is_the_market_source(make_client):
    client, state = make_client()

    async def ping():
        return True

    state.redis = SimpleNamespace(ping=ping)
    body = (await client.get("/api/health")).json()
    assert (body["redis"], body["market_source"]) == ("ok", "redis")


async def test_an_unreachable_redis_makes_health_degraded(make_client):
    client, state = make_client()

    async def ping():
        raise redis_errors.ConnectionError("down")

    state.redis = SimpleNamespace(ping=ping)
    response = await client.get("/api/health")
    assert (response.status_code, response.json()["redis"]) == (503, "unreachable")


async def test_a_busy_assistant_refuses_instead_of_queueing(make_client):
    client, state = enable_chat(make_client, [say("ok")])
    state.chat_slots = asyncio.Semaphore(0)
    assert (await client.post("/api/chat", json={"question": "anything here"})).status_code == 429


async def test_assistant_failures_are_a_502_without_details(make_client):
    client, _ = enable_chat(make_client, [say("")])  # an empty answer
    response = await client.post("/api/chat", json={"question": "anything here"})
    assert (response.status_code, response.json()["detail"]) == (
        502,
        "the assistant could not answer",
    )

    error = openai.APIConnectionError(request=httpx.Request("POST", "https://api.example/v1"))
    client, _ = enable_chat(make_client, [error])
    response = await client.post("/api/chat", json={"question": "anything here"})
    assert (response.status_code, response.json()["detail"]) == (
        502,
        "the AI service is unavailable",
    )
