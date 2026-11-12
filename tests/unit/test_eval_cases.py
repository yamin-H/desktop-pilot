import json
from pathlib import Path

import pytest

from deskpilot.agent import ToolContext, build_default_registry
from deskpilot.evals.cases import CASES
from deskpilot.evals.data import NOW, eval_data

STATEMENTS = Path(__file__).resolve().parents[2] / "data" / "eval_statements"
REGISTRY = build_default_registry()
CONTEXT = ToolContext(data=eval_data(), statements_dir=STATEMENTS, clock=lambda: NOW)


def test_there_are_thirty_cases_with_unique_ids():
    assert len(CASES) == 30
    assert len({case.id for case in CASES}) == 30


def test_every_expected_tool_exists():
    for case in CASES:
        assert set(case.expected_tools) <= set(REGISTRY.names), case.id


DAY = {"start": "2026-11-10", "end": "2026-11-11"}

HAND_NUMBERS = [
    ("get_positions", {}, ["0.3495", "60393.93", "3003.00", "21107.68"]),
    ("get_pnl", {}, ["2057.05", "1051.82", "1728.25", "141.00", "22018.50", "1005.23"]),
    ("get_realized_pnl", DAY, ["1005.23", "817.43", "187.80"]),
    (
        "get_realized_pnl",
        {"start": "2026-11-10T14:00:00Z", "end": "2026-11-10T16:00:00Z"},
        ["817.43"],
    ),
    ("get_latest_price", {"exchange": "binance", "symbol": "BTC/USDT"}, ["63000"]),
    ("get_latest_price", {"exchange": "binance", "symbol": "ETH/USDT"}, ["3050"]),
    (
        "run_reconciliation",
        {"exchange": "binance", "statement_file": "binance_2026-11-10_with_errors.csv", **DAY},
        ["PAPER-0001", "PAPER-0002", "PAPER-0003", "PAPER-0099", "0.75"],
    ),
]


@pytest.mark.parametrize(("tool", "arguments", "expected"), HAND_NUMBERS)
async def test_the_calculator_agrees_with_the_hand_numbers(tool, arguments, expected):
    result = json.dumps(await REGISTRY.call(tool, json.dumps(arguments), CONTEXT))
    for item in expected:
        assert item in result, f"{tool}: {item} not found"


async def test_a_day_without_sales_has_no_realized_profit():
    args = {"start": "2026-11-11", "end": "2026-11-12"}
    result = await REGISTRY.call("get_realized_pnl", json.dumps(args), CONTEXT)
    assert result["sales_in_period"] == 0
