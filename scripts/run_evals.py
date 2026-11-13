"""Run the golden questions against the real model and score the answers.

Usage:
  uv run python scripts/run_evals.py                          # all 30 questions
  uv run python scripts/run_evals.py --only pnl-total refuse-trade
  uv run python scripts/run_evals.py --repeat 3 --markdown

Needs LLM_API_KEY and LLM_MODEL in .env. No database is needed: the questions run on fixed
in-memory data (src/deskpilot/evals/dataset.py) with a fixed clock.
"""

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import openai

from deskpilot.agent import (
    Agent,
    AgentConfigError,
    StaticData,
    ToolContext,
    build_default_registry,
    make_client,
    require_model,
)
from deskpilot.config import get_settings
from deskpilot.evals import (
    EVAL_NOW,
    EVAL_PRICES,
    PAPER_TRADES,
    RunResult,
    clock_numbers,
    format_markdown,
    format_report,
    load_golden_questions,
    run_evaluation,
    write_transcript,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "agent_evals" / "golden_questions.yaml"
STATEMENTS = ROOT / "data" / "statements"
RUNS = ROOT / "eval_runs"


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        client = make_client(settings)
        model = args.model or require_model(settings)
    except AgentConfigError as error:
        print(error)
        return 2

    questions = load_golden_questions(GOLDEN)
    if args.only:
        known = {question.id for question in questions}
        unknown = [name for name in args.only if name not in known]
        if unknown:
            print(f"unknown question id(s): {', '.join(unknown)}")
            await client.close()
            return 2
        questions = [question for question in questions if question.id in set(args.only)]

    context = ToolContext(
        data=StaticData(PAPER_TRADES, EVAL_PRICES),
        statements_dir=STATEMENTS,
        clock=lambda: EVAL_NOW,
    )
    agent = Agent(client, model, build_default_registry(), context)

    total = len(questions) * args.repeat
    finished = 0

    def show(result: RunResult) -> None:
        nonlocal finished
        finished += 1
        status = "ERROR" if result.error else ("PASS" if result.passed else "FAIL")
        print(
            f"[{finished:>2}/{total}] {result.question.id:<24} {status:<5} "
            f"{result.seconds:>5.1f}s  {result.steps} request(s)",
            flush=True,
        )

    try:
        results = await run_evaluation(
            agent,
            questions,
            repeat=args.repeat,
            delay=args.delay,
            extra_numbers=clock_numbers(EVAL_NOW),
            provider_errors=(openai.OpenAIError,),
            on_result=show,
        )
    finally:
        await client.close()

    print()
    print(format_report(results, model=model))
    if args.markdown:
        print()
        print(format_markdown(results, model=model))

    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    path = RUNS / f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{safe_model}.jsonl"
    write_transcript(results, path)
    print(f"\nfull transcripts: {path}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score the assistant on the golden questions.")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these question ids")
    parser.add_argument("--repeat", type=int, default=1, help="ask each question this many times")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds to pause between runs")
    parser.add_argument("--model", help="override LLM_MODEL from .env")
    parser.add_argument("--markdown", action="store_true", help="also print a README-ready table")
    arguments = parser.parse_args()
    if arguments.repeat < 1:
        parser.error("--repeat must be at least 1")
    sys.exit(asyncio.run(main(arguments)))
