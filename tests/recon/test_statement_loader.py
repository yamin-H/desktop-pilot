from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.models import Exchange, Side
from deskpilot.recon.loader import StatementError, parse_statement, read_statement

HEADER = "trade_id,symbol,side,quantity,price,fee,fee_asset,executed_at\n"
GOOD_ROW = "T-1,BTC/USDT,buy,0.002,60000.10,0.12,USDT,2026-01-01T12:00:00Z\n"


def test_reads_a_trade():
    [trade] = parse_statement(HEADER + GOOD_ROW, Exchange.BINANCE)
    assert trade.exchange is Exchange.BINANCE
    assert trade.trade_id == "T-1"
    assert trade.symbol == "BTC/USDT"
    assert trade.side is Side.BUY
    assert trade.quantity == Decimal("0.002")
    assert trade.price == Decimal("60000.10")
    assert trade.fee == Decimal("0.12")
    assert trade.fee_asset == "USDT"
    assert trade.executed_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_a_header_with_no_rows_is_an_empty_statement():
    assert parse_statement(HEADER, Exchange.BINANCE) == []


def test_column_names_may_have_any_case_spacing_and_order():
    text = (
        " Executed_At , TRADE_ID,fee,Price,quantity,side,symbol \n"
        "2026-01-01T12:00:00Z,T-1,0,100,1,SELL,eth/usdt\n"
    )
    [trade] = parse_statement(text, Exchange.KRAKEN)
    assert trade.exchange is Exchange.KRAKEN
    assert (trade.symbol, trade.side) == ("ETH/USDT", Side.SELL)


def test_a_blank_fee_and_currency_mean_no_fee():
    text = HEADER + "T-1,BTC/USDT,buy,1,100,,,2026-01-01T12:00:00Z\n"
    [trade] = parse_statement(text, Exchange.BINANCE)
    assert trade.fee == 0
    assert trade.fee_asset is None


def test_the_fee_currency_column_is_optional():
    text = (
        "trade_id,symbol,side,quantity,price,fee,executed_at\n"
        "T-1,BTC/USDT,buy,1,100,0,2026-01-01T12:00:00Z\n"
    )
    [trade] = parse_statement(text, Exchange.BINANCE)
    assert trade.fee_asset is None


def test_extra_columns_are_ignored():
    text = "note," + HEADER.strip() + "\nhello," + GOOD_ROW
    assert len(parse_statement(text, Exchange.BINANCE)) == 1


def test_times_with_an_offset_are_converted_to_utc():
    text = HEADER + "T-1,BTC/USDT,buy,1,100,0,,2026-01-01T18:00:00+06:00\n"
    [trade] = parse_statement(text, Exchange.BINANCE)
    assert trade.executed_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_an_empty_file_is_refused():
    with pytest.raises(StatementError, match="empty"):
        parse_statement("", Exchange.BINANCE)


def test_a_missing_column_is_refused_and_named():
    with pytest.raises(StatementError, match="quantity"):
        parse_statement("trade_id,symbol,side\nT-1,BTC/USDT,buy\n", Exchange.BINANCE)


def test_every_bad_row_is_reported_with_its_line_number():
    text = (
        HEADER
        + "T-1,BTC/USDT,buy,0.002,60000,0,,2026-01-01T12:00:00Z\n"  # line 2: fine
        + "T-2,BTC/USDT,hold,1,60000,0,,2026-01-01T12:00:00Z\n"  # line 3: bad side
        + "T-3,BTC/USDT,buy,0,60000,0,,2026-01-01T12:00:00Z\n"  # line 4: zero quantity
    )
    with pytest.raises(StatementError) as info:
        parse_statement(text, Exchange.BINANCE)
    problems = info.value.problems
    assert len(problems) == 2
    assert problems[0].startswith("line 3:") and "side" in problems[0]
    assert problems[1].startswith("line 4:") and "quantity" in problems[1]


@pytest.mark.parametrize(
    "row",
    [
        "T-1,BTC/USDT,buy,1,100,0,,yesterday",  # not a time
        "T-1,BTC/USDT,buy,1,100,0,,2026-01-01T12:00:00",  # no timezone
        "T-1,BTC/USDT,buy,1,-100,0,,2026-01-01T12:00:00Z",  # negative price
        "T-1,BTC/USDT,buy,abc,100,0,,2026-01-01T12:00:00Z",  # not a number
        "T-1,BTC/USDT,buy,1,100,-1,,2026-01-01T12:00:00Z",  # negative fee
        "T-1,BTCUSDT,buy,1,100,0,,2026-01-01T12:00:00Z",  # bad symbol
        ",BTC/USDT,buy,1,100,0,,2026-01-01T12:00:00Z",  # no trade id
        "T-1,BTC/USDT,buy",  # too few columns
        "T-1,BTC/USDT,buy,1,100,0,,2026-01-01T12:00:00Z,surprise",  # too many columns
    ],
)
def test_unreadable_rows_are_refused(row):
    with pytest.raises(StatementError):
        parse_statement(HEADER + row + "\n", Exchange.BINANCE)


def test_a_statement_file_can_be_read_even_with_an_excel_marker(tmp_path):
    path = tmp_path / "statement.csv"
    path.write_text("\ufeff" + HEADER + GOOD_ROW, encoding="utf-8")
    [trade] = read_statement(path, Exchange.BINANCE)
    assert trade.trade_id == "T-1"
