# The assistant

A question goes in, a plain-English answer comes out. The model never does the maths:
it asks tools, our code runs them, and the model explains the results.

## Rules the assistant follows (see agent/prompts.py)
1. Every number comes from a tool result. No calculating, rounding or adding up.
2. Facts about the desk come only from tools. If no tool can answer, it says so.
3. null means unknown, never zero. Stale prices are mentioned.
4. Tool errors are explained, never papered over with a guess.
5. Read-only: it cannot trade, change records or fix mismatches.
6. Money always has its currency next to it.

## Tools (all read-only)
| Tool | Answers |
|---|---|
| get_positions | what we hold: quantity, average cost, cost basis, realized profit |
| get_pnl | realized + unrealized profit (latest recorded Binance price), totals per currency |
| get_realized_pnl | profit locked in by sales inside a time period |
| get_latest_price | newest recorded price on an exchange, and its age |
| list_trades | newest trades, with filters |
| run_reconciliation | compare the ledger with a statement CSV and list breaks |

## How the safety works
- Tools return finished numbers as TEXT ("817.43"), rounded to cents. Quantities and
  prices keep every digit. The model only copies them.
- Arguments are typed (Pydantic) and the JSON schema sent to the model is generated from
  the same definition. Unknown arguments are rejected.
- A tool problem comes back as {"error": "..."} so the model can explain or retry. A bug
  is logged with its traceback; the model only sees a generic "do not guess" message.
- Statement files: plain `.csv` names inside data/statements/ only. Folders, "..",
  absolute paths and symlinks leading outside are refused.
- Temperature 0, and a limit of 6 requests per question.

## Provider
OpenAI SDK with base_url = Groq. Change LLM_BASE_URL, LLM_API_KEY and LLM_MODEL to use
another OpenAI-compatible provider. The model must support tool calling.

## Known limits
- Prices are shown to cents in derived values; coins priced below a cent would need more.
- Unrealized profit uses one reference price per coin pair (latest recorded Binance).
- One question at a time: no conversation memory yet.
- How faithfully a model obeys "no arithmetic" is MEASURED by the evaluation harness
  (next step), not assumed.