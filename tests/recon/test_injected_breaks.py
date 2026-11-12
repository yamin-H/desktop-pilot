from collections import Counter

import pytest

from deskpilot.recon.injection import PLAN, build_scenario
from deskpilot.recon.matcher import reconcile


def check(scenario, ledger=None):
    return reconcile(
        scenario.ledger if ledger is None else ledger,
        scenario.statement,
        exchange=scenario.exchange,
        start=scenario.start,
        end=scenario.end,
    )


def test_the_scenario_injects_twenty_mistakes_on_twenty_different_trades():
    scenario = build_scenario()
    assert len(scenario.injected) == 20
    assert len({item.trade_id for item in scenario.injected}) == 20


@pytest.mark.parametrize("seed", range(25))
def test_all_twenty_mistakes_are_found_and_nothing_else(seed):
    scenario = build_scenario(seed=seed)
    report = check(scenario)

    found = Counter((item.kind, item.trade_id) for item in report.breaks)
    expected = Counter((item.kind, item.trade_id) for item in scenario.injected)

    # Same mistakes, each exactly once: none missed, and no false alarms.
    assert found == expected
    assert len(report.breaks) == 20


def test_the_counts_per_kind_match_the_plan():
    planned = Counter()
    for _, kind, number in PLAN:
        planned[kind] += number
    assert check(build_scenario()).counts() == dict(planned)


def test_the_untouched_trades_come_out_clean():
    report = check(build_scenario())
    # 60 trades. 3 only on the statement and 3 only in the ledger leave 54 matched.
    # 13 of those have a differing field (2+2+2+2+2+1+2); the duplicate pair itself is fine.
    assert report.statement_trades == 57
    assert report.ledger_trades == 57
    assert report.matched == 54
    assert report.matched_clean == 54 - 13


def test_a_ledger_identical_to_the_statement_gives_a_clean_report():
    scenario = build_scenario()
    unique_statement = list({trade.trade_id: trade for trade in scenario.statement}.values())
    assert check(scenario, ledger=unique_statement).is_clean


def test_the_same_seed_gives_the_same_scenario():
    assert build_scenario(seed=3) == build_scenario(seed=3)


def test_too_few_trades_are_refused():
    with pytest.raises(ValueError):
        build_scenario(trade_count=19)