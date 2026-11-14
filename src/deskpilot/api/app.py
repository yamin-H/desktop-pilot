import asyncio
import json
import logging
import math
import secrets
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import openai
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis import exceptions as redis_errors

from deskpilot.agent import (
    Agent,
    AgentError,
    DatabaseData,
    ToolContext,
    ToolRegistry,
    build_default_registry,
    make_client,
)
from deskpilot.agent.tools.common import ExchangeName, iso
from deskpilot.analytics import PriceBoard
from deskpilot.api.limits import RateLimiter
from deskpilot.api.market import (
    DatabaseMarketSource,
    market_events,
    market_snapshot,
    run_market_poller,
)
from deskpilot.bus import MarketFollower, make_redis
from deskpilot.clerk.models import Classified
from deskpilot.clerk.store import AnnouncementStore
from deskpilot.config import Settings, get_settings
from deskpilot.storage import create_pool

logger = logging.getLogger(__name__)

STATEMENTS_DIR = Path(__file__).resolve().parents[3] / "data" / "statements"


class AnnouncementSource(Protocol):
    async def list_recent(
        self, limit: int = 20, *, important_only: bool = False
    ) -> list[Classified]: ...


@dataclass
class ApiState:
    settings: Settings
    board: PriceBoard
    context: ToolContext
    registry: ToolRegistry
    announcements: AnnouncementSource
    pool: asyncpg.Pool | None = None
    agent: Agent | None = None
    poller: asyncio.Task | None = None
    chat_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10, 60))
    chat_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    stream_interval: float = 1.0
    stream_limit: int | None = None
    max_streams: int = 50
    active_streams: int = 0
    redis: Any = None


def state_of(request: Request) -> ApiState:
    return request.app.state.api


def require_token(request: Request) -> None:
    token = state_of(request).settings.api_token
    if not token:
        return
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "missing or wrong token", headers={"WWW-Authenticate": "Bearer"})


async def run_tool(request: Request, name: str, **arguments: Any) -> dict[str, Any]:
    """Run one of the assistant's tools, so the dashboard and the assistant never disagree."""
    state = state_of(request)
    sent = {key: value for key, value in arguments.items() if value is not None}
    result = await state.registry.call(name, json.dumps(sent), state.context)
    error = result.get("error")
    if error is not None:
        if error.startswith("internal error"):
            raise HTTPException(500, "internal error")
        raise HTTPException(422, error)
    return result


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ToolUse(BaseModel):
    name: str
    arguments: str
    ok: bool


class ChatResponse(BaseModel):
    answer: str
    tools: list[ToolUse]


public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@public.get("/health")
async def health(request: Request) -> JSONResponse:
    state = state_of(request)
    database = "unknown"
    if state.pool is not None:
        try:
            await asyncio.wait_for(state.pool.fetchval("SELECT 1"), timeout=2)
            database = "ok"
        except (OSError, TimeoutError, asyncpg.PostgresError):
            database = "unreachable"
    redis = "off"
    if state.redis is not None:
        try:
            await asyncio.wait_for(state.redis.ping(), timeout=2)
            redis = "ok"
        except (OSError, TimeoutError, redis_errors.RedisError):
            redis = "unreachable"
    poller_ok = state.poller is None or not state.poller.done()
    healthy = database != "unreachable" and redis != "unreachable" and poller_ok
    body = {
        "status": "ok" if healthy else "degraded",
        "database": database,
        "redis": redis,
        "market_source": "redis" if state.redis is not None else "database",
        "market_poller": "running" if poller_ok else "stopped",
        "time": iso(datetime.now(UTC)),
    }
    return JSONResponse(body, status_code=200 if healthy else 503)


@router.get("/config")
async def config(request: Request) -> dict[str, Any]:
    state = state_of(request)
    return {"chat_enabled": bool(state.settings.api_enable_chat and state.agent is not None)}


@router.get("/market")
async def market(request: Request) -> dict[str, Any]:
    return market_snapshot(state_of(request).board)


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    state = state_of(request)
    if state.active_streams >= state.max_streams:
        raise HTTPException(503, "too many live connections, try again shortly")

    async def events():
        state.active_streams += 1
        try:
            async for chunk in market_events(
                state.board, interval=state.stream_interval, limit=state.stream_limit
            ):
                yield chunk
        finally:
            state.active_streams -= 1

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/positions")
async def positions(
    request: Request, exchange: ExchangeName | None = None, symbol: str | None = None
) -> dict[str, Any]:
    return await run_tool(request, "get_positions", exchange=exchange, symbol=symbol)


@router.get("/pnl")
async def pnl(
    request: Request, exchange: ExchangeName | None = None, symbol: str | None = None
) -> dict[str, Any]:
    return await run_tool(request, "get_pnl", exchange=exchange, symbol=symbol)


@router.get("/realized")
async def realized(
    request: Request,
    start: str,
    end: str,
    exchange: ExchangeName | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    return await run_tool(
        request, "get_realized_pnl", start=start, end=end, exchange=exchange, symbol=symbol
    )


@router.get("/trades")
async def trades(
    request: Request,
    exchange: ExchangeName | None = None,
    symbol: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return await run_tool(request, "list_trades", exchange=exchange, symbol=symbol, limit=limit)


@router.get("/recon")
async def recon(
    request: Request, exchange: ExchangeName, statement: str, start: str, end: str
) -> dict[str, Any]:
    return await run_tool(
        request,
        "run_reconciliation",
        exchange=exchange,
        statement_file=statement,
        start=start,
        end=end,
    )


@router.get("/announcements")
async def announcements(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    important_only: bool = False,
) -> dict[str, Any]:
    items = await state_of(request).announcements.list_recent(limit, important_only=important_only)
    return {
        "count": len(items),
        "announcements": [
            {
                "source": item.announcement.source,
                "title": item.announcement.title,
                "url": item.announcement.url,
                "category": item.category.value,
                "assets": list(item.assets),
                "important": item.important,
                "time": iso(item.announcement.published_at)
                if item.announcement.published_at
                else None,
            }
            for item in items
        ],
    }


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    state = state_of(request)
    if not state.settings.api_enable_chat:
        raise HTTPException(403, "chat is disabled on this server")
    if state.agent is None:
        raise HTTPException(503, "the assistant is not configured (LLM_API_KEY and LLM_MODEL)")
    wait = state.chat_limiter.try_acquire()
    if wait is not None:
        raise HTTPException(
            429,
            "too many questions, try again shortly",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    if state.chat_slots.locked():
        raise HTTPException(429, "the assistant is busy, try again shortly")

    async with state.chat_slots:
        try:
            answer = await state.agent.ask(body.question)
        except AgentError as error:
            logger.warning("assistant failed: %s", error)
            raise HTTPException(502, "the assistant could not answer") from None
        except openai.OpenAIError as error:
            logger.warning("AI service error: %s: %s", type(error).__name__, error)
            raise HTTPException(502, "the AI service is unavailable") from None
    return ChatResponse(
        answer=answer.text,
        tools=[
            ToolUse(name=r.name, arguments=r.arguments, ok=not r.failed) for r in answer.tool_calls
        ],
    )


def create_app(state: ApiState | None = None) -> FastAPI:
    """The API. With no `state` (production) everything is built when the server starts."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state is not None:
            yield
            return

        settings = get_settings()
        pool = await create_pool(settings.database_url)
        board = PriceBoard(max_age=30)
        context = ToolContext(
            data=DatabaseData(pool),
            statements_dir=STATEMENTS_DIR,
            clock=lambda: datetime.now(UTC),
        )
        registry = build_default_registry()
        client = agent = None
        if settings.api_enable_chat and settings.llm_api_key and settings.llm_model:
            client = make_client(settings)
            agent = Agent(client, settings.llm_model, registry, context)
        built = ApiState(
            settings=settings,
            board=board,
            context=context,
            registry=registry,
            announcements=AnnouncementStore(pool),
            pool=pool,
            agent=agent,
        )
        redis = None
        if settings.use_redis:  # live prices come from the stream
            redis = make_redis(settings.redis_url)
            built.redis = redis
            follower = MarketFollower(redis, board, stream=settings.tick_stream)
            built.poller = asyncio.create_task(follower.run())
        else:  # live prices come from the database
            built.poller = asyncio.create_task(run_market_poller(DatabaseMarketSource(pool), board))
        app.state.api = built
        try:
            yield
        finally:
            built.poller.cancel()
            with suppress(asyncio.CancelledError):
                await built.poller
            await pool.close()
            if redis is not None:
                await redis.aclose()
            if client is not None:
                await client.close()

    app = FastAPI(
        title="DeskPilot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    if state is not None:
        app.state.api = state
    app.include_router(public)
    app.include_router(router)
    return app
