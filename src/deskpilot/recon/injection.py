"""Builds a ledger and a statement with a known set of mistakes, to prove the Checker finds them."""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from deskpilot.models import Exchange, Side, Trade
from deskpilot.recon.rules import BreakKind

START = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)

# (what we do to a trade, the break the Checker must report, how many times)
PLAN: tuple[tuple[str, BreakKind, int], ...] = (
    ("missing_in_ledger", BreakKind.MISSING_IN_LEDGER, 3),
    ("missing_in_statement", BreakKind.MISSING_IN_STATEMENT, 3),
    ("duplicate_in_statement", BreakKind.DUPLICATE_IN_STATEMENT, 1),
    ("symbol", BreakKind.SYMBOL_MISMATCH, 2),
    ("side", BreakKind.SIDE_MISMATCH, 2),
    ("quantity", BreakKind.QUANTITY_MISMATCH, 2),
    ("price", BreakKind.PRICE_MISMATCH, 2),
    ("fee_amount", BreakKind.FEE_MISMATCH, 2),
    ("fee_asset", BreakKind.FEE_MISMATCH, 1),
    ("time", BreakKind.TIME_DRIFT, 2),
)

_PRICE_RANGES = {"BTC/USDT": (50_000, 70_000), "ETH/USDT": (2_000, 4_000)}


@dataclass(frozen=True)
class Injected:
    """One mistake we deliberately put in."""

    mutation: str
    kind: BreakKind  # the break the Checker is expected to report for it
    trade_id: str


@dataclass(frozen=True)
class Scenario:
    exchange: Exchange
    start: datetime
    end: datetime
    ledger: tuple[Trade, ...]
    statement: tuple[Trade, ...]
    injected: tuple[Injected, ...]


def _base_trades(rng: random.Random, count: int) -> list[Trade]:
    trades = []
    for index in range(count):
        symbol = rng.choice(sorted(_PRICE_RANGES))
        low, high = _PRICE_RANGES[symbol]
        quantity = Decimal(rng.randint(1, 500)) / 1000  # 0.001 to 0.500
        price = Decimal(rng.randint(low * 100, high * 100)) / 100  # to the cent
        fee = (quantity * price * Decimal("0.001")).quantize(Decimal("0.00000001"))
        trades.append(
            Trade(
                exchange=Exchange.BINANCE,
                trade_id=f"INJ-{index:04d}",
                symbol=symbol,
                side=rng.choice(["buy", "sell"]),
                quantity=quantity,
                price=price,
                fee=fee,
                fee_asset="USDT",
                executed_at=START + timedelta(minutes=index),
            )
        )
    return trades


def _changed(trade: Trade, **changes) -> Trade:
    return Trade.model_validate({**trade.model_dump(), **changes})


def _mutate(mutation: str, trade: Trade) -> Trade:
    """The statement's (wrong) version of a trade."""
    if mutation == "symbol":
        return _changed(trade, symbol="ETH/USDT" if trade.symbol == "BTC/USDT" else "BTC/USDT")
    if mutation == "side":
        return _changed(trade, side=Side.SELL if trade.side is Side.BUY else Side.BUY)
    if mutation == "quantity":
        return _changed(trade, quantity=trade.quantity + Decimal("0.001"))
    if mutation == "price":
        return _changed(trade, price=trade.price + Decimal("1"))
    if mutation == "fee_amount":
        return _changed(trade, fee=trade.fee + Decimal("0.01"))
    if mutation == "fee_asset":
        return _changed(trade, fee_asset="BNB")
    if mutation == "time":
        return _changed(trade, executed_at=trade.executed_at + timedelta(seconds=5))
    raise ValueError(f"unknown mutation {mutation!r}")


def build_scenario(seed: int = 7, trade_count: int = 60) -> Scenario:
    """A ledger and a statement that disagree in exactly the ways listed in PLAN."""
    total = sum(number for _, _, number in PLAN)
    if trade_count < total:
        raise ValueError(f"need at least {total} trades to inject {total} mistakes")

    rng = random.Random(seed)
    base = _base_trades(rng, trade_count)

    # Each mistake goes on a different trade, so every break can be told apart.
    targets = iter(rng.sample(range(trade_count), total))
    plan_for_index = {
        next(targets): (mutation, kind) for mutation, kind, number in PLAN for _ in range(number)
    }

    ledger: list[Trade] = []
    statement: list[Trade] = []
    injected: list[Injected] = []
    for index, trade in enumerate(base):
        plan = plan_for_index.get(index)
        if plan is None:
            ledger.append(trade)
            statement.append(trade)
            continue

        mutation, kind = plan
        injected.append(Injected(mutation, kind, trade.trade_id))
        if mutation == "missing_in_ledger":
            statement.append(trade)  # only the exchange has it
        elif mutation == "missing_in_statement":
            ledger.append(trade)  # only we have it
        elif mutation == "duplicate_in_statement":
            ledger.append(trade)
            statement.extend([trade, trade])
        else:
            ledger.append(trade)
            statement.append(_mutate(mutation, trade))

    return Scenario(
        exchange=Exchange.BINANCE,
        start=START,
        end=START + timedelta(minutes=trade_count),
        ledger=tuple(ledger),
        statement=tuple(statement),
        injected=tuple(injected),
    )
