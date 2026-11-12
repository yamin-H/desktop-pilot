"""Inject 20 known mistakes, run the Checker, and show how many it finds.

Usage: uv run python scripts/inject_breaks.py [seed] [trade_count]
Try a big one: uv run python scripts/inject_breaks.py 7 20000
"""

import sys
import time
from collections import Counter

from deskpilot.recon.injection import PLAN, build_scenario
from deskpilot.recon.matcher import reconcile


def main(seed: int, trade_count: int) -> int:
    scenario = build_scenario(seed=seed, trade_count=trade_count)

    started = time.perf_counter()
    report = reconcile(
        scenario.ledger,
        scenario.statement,
        exchange=scenario.exchange,
        start=scenario.start,
        end=scenario.end,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    expected = Counter((item.kind, item.trade_id) for item in scenario.injected)
    found = Counter((item.kind, item.trade_id) for item in report.breaks)
    detected = expected & found
    missed = expected - found
    false_alarms = found - expected

    print(f"{'mistake injected':<26}{'expected break':<26}{'injected':>9}{'found':>7}")
    for mutation, kind, _ in PLAN:
        ids = [item.trade_id for item in scenario.injected if item.mutation == mutation]
        hits = sum(1 for trade_id in ids if (kind, trade_id) in detected)
        print(f"{mutation:<26}{kind.value:<26}{len(ids):>9}{hits:>7}")
    print("-" * 68)
    print(f"{'TOTAL':<52}{sum(expected.values()):>9}{sum(detected.values()):>7}")
    print()
    print(f"missed: {sum(missed.values())}   false alarms: {sum(false_alarms.values())}")
    print(
        f"checked {report.ledger_trades} ledger trades against "
        f"{report.statement_trades} statement trades in {elapsed_ms:.1f} ms"
    )
    return 0 if not missed and not false_alarms else 1


if __name__ == "__main__":
    sys.exit(
        main(
            int(sys.argv[1]) if len(sys.argv) > 1 else 7,
            int(sys.argv[2]) if len(sys.argv) > 2 else 60,
        )
    )