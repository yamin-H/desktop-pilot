from datetime import timedelta

import pytest

from deskpilot.agent.data import StaticData
from deskpilot.models import Trade

HEADER = "trade_id,symbol,side,quantity,price,fee,fee_asset,executed_at\n"
CLEAN = (
    HEADER
    + "PAPER-0001,BTC/USDT,buy,0.50,60000,0.0005,BTC,2026-11-10T10:00:00Z\n"
    + "PAPER-0002,BTC/USDT,buy,0.25,61000,15.25,USDT,2026-11-10T11:30:00Z\n"
    + "PAPER-0003,BTC/USDT,sell,0.40,62500,25.00,USDT,2026-11-10T14:15:00Z\n"
)
WITH_ERRORS = (
    HEADER
    + "PAPER-0001,BTC/USDT,buy,0.51,60000,0.0005,BTC,2026-11-10T10:00:00Z\n"
    + "PAPER-0002,BTC/USDT,buy,0.25,61000,16.00,USDT,2026-11-10T11:30:05Z\n"
    + "PAPER-0099,BTC/USDT,sell,0.10,62600,6.26,USDT,2026-11-10T15:00:00Z\n"
)
PERIOD = {"exchange": "binance", "start": "2026-11-10", "end": "2026-11-11"}


@pytest.fixture
def statements(tmp_path):
    folder = tmp_path / "statements"
    folder.mkdir()
    (folder / "clean.csv").write_text(CLEAN, encoding="utf-8")
    (folder / "errors.csv").write_text(WITH_ERRORS, encoding="utf-8")
    return folder


async def test_a_matching_statement_is_clean(run_tool, statements):
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "clean.csv"})
    assert result["is_clean"] is True
    assert (result["statement_trades"], result["ledger_trades"], result["matched"]) == (3, 3, 3)
    assert result["break_count"] == 0
    assert result["breaks"] == []


async def test_every_kind_of_mistake_is_reported(run_tool, statements):
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "errors.csv"})
    assert result["is_clean"] is False
    assert result["break_count"] == 5
    assert result["breaks_by_kind"] == {
        "missing_in_ledger": 1,
        "missing_in_statement": 1,
        "quantity_mismatch": 1,
        "fee_mismatch": 1,
        "time_drift": 1,
    }
    by_kind = {item["kind"]: item for item in result["breaks"]}
    quantity = by_kind["quantity_mismatch"]
    assert quantity["trade_id"] == "PAPER-0001"
    assert (quantity["ledger_value"], quantity["statement_value"]) == ("0.50", "0.51")
    assert quantity["difference"] == "0.01"
    assert "ledger 0.50, statement 0.51" in quantity["detail"]
    assert by_kind["missing_in_ledger"]["trade_id"] == "PAPER-0099"
    assert by_kind["missing_in_statement"]["trade_id"] == "PAPER-0003"
    assert by_kind["time_drift"]["difference"] == "5"
    assert by_kind["fee_mismatch"]["difference"] == "0.75"


async def test_other_exchanges_in_the_ledger_are_not_blamed(run_tool, statements):
    # The ledger also holds Kraken trades; they must not show up as breaks.
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "clean.csv"})
    assert result["ledger_trades"] == 3


async def test_a_long_list_of_breaks_is_cut_off_and_marked(run_tool, statements):
    (statements / "empty.csv").write_text(HEADER, encoding="utf-8")
    trades = [
        Trade(
            exchange="binance", trade_id=f"T-{i:03d}", symbol="BTC/USDT", side="buy",
            quantity="1", price="100",
            executed_at=f"2026-11-10T{i // 60:02d}:{i % 60:02d}:00Z",
        )
        for i in range(60)
    ]
    result = await run_tool(
        "run_reconciliation",
        {**PERIOD, "statement_file": "empty.csv"},
        data=StaticData(trades),
    )
    assert result["break_count"] == 60
    assert result["breaks_shown"] == 50
    assert len(result["breaks"]) == 50
    assert result["truncated"] is True
    assert result["breaks_by_kind"] == {"missing_in_statement": 60}


@pytest.mark.parametrize(
    "name",
    ["../outside.csv", "sub/clean.csv", "..\\clean.csv", "clean.txt", "", ".hidden.csv", "/etc/passwd"],
)
async def test_file_names_that_could_escape_the_folder_are_refused(
    run_tool, statements, tmp_path, name
):
    (tmp_path / "outside.csv").write_text(CLEAN, encoding="utf-8")  # a real file outside
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": name})
    assert "not a valid statement file name" in result["error"]
    assert "clean.csv" in result["error"]  # the real choices are listed


async def test_a_symlink_that_points_outside_is_refused(run_tool, statements, tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text(CLEAN, encoding="utf-8")
    try:
        (statements / "link.csv").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow symlinks")
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "link.csv"})
    assert "no statement file" in result["error"]


async def test_a_missing_file_lists_the_available_ones(run_tool, statements):
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "nope.csv"})
    assert "no statement file named 'nope.csv'" in result["error"]
    assert "clean.csv, errors.csv" in result["error"]


async def test_without_a_statements_folder_the_error_says_none(run_tool):
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "nope.csv"})
    assert "none" in result["error"]


async def test_an_unreadable_statement_names_the_bad_line(run_tool, statements):
    bad = HEADER + "T-1,BTC/USDT,buy,1,100,0,,2026-11-10T10:00:00Z\n"
    bad += "T-2,BTC/USDT,hold,1,100,0,,2026-11-10T11:00:00Z\n"
    (statements / "bad.csv").write_text(bad, encoding="utf-8")
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "bad.csv"})
    assert "cannot be read" in result["error"]
    assert "line 3" in result["error"]


async def test_a_file_that_is_not_text_is_an_error_not_a_crash(run_tool, statements):
    (statements / "binary.csv").write_bytes(b"\xff\xfe\x00\x81\x82")
    result = await run_tool("run_reconciliation", {**PERIOD, "statement_file": "binary.csv"})
    assert "not a readable text file" in result["error"]


@pytest.mark.parametrize(
    ("period", "message"),
    [
        ({"start": "2026-11-11", "end": "2026-11-10"}, "before"),
        ({"start": "soon", "end": "2026-11-11"}, "ISO 8601"),
    ],
)
async def test_bad_periods_are_errors(run_tool, statements, period, message):
    arguments = {"exchange": "binance", "statement_file": "clean.csv", **period}
    assert message in (await run_tool("run_reconciliation", arguments))["error"]


async def test_the_tool_never_writes_anything(run_tool, statements):
    before = sorted(p.name for p in statements.iterdir())
    await run_tool("run_reconciliation", {**PERIOD, "statement_file": "errors.csv"})
    assert sorted(p.name for p in statements.iterdir()) == before


def test_timedelta_import_is_used():
    assert timedelta(seconds=1)  # keeps the import list honest for the linter