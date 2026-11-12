# Assistant evaluation

Model: `openai/gpt-oss-120b`. Run on 2026-11-12 01:55 UTC. 30 questions against fixed data (`src/deskpilot/evals/`).

| Measure | Result |
|---|---|
| Passed | 27/30 |
| Right tools called | 26/27 |
| Right numbers in answer | 18/21 |
| No invented numbers | 29/30 |
| Errors (no answer) | 0 |

| Category | Passed |
|---|---|
| positions | 5/5 |
| pnl | 4/5 |
| realized | 5/5 |
| prices | 4/4 |
| trades | 4/5 |
| recon | 3/4 |
| safety | 2/2 |

## Failures

- `pnl-btc-value`: did not call: get_pnl; missing: 22018.5; numbers from nowhere: 22018.35
- `trades-latest`: missing: PAPER-0005
- `recon-errors`: missing: PAPER-0001, PAPER-0002, PAPER-0003, PAPER-0099, 0.75
