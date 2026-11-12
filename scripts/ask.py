"""Ask the DeskPilot assistant a question about the trades in the database.

Usage: uv run python scripts/ask.py "What are our positions?"

Needs LLM_API_KEY and LLM_MODEL in .env, and a running database (make db-up).
Statement files for reconciliation are read from data/statements/.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import openai

from deskpilot.agent import (
    Agent,
    AgentConfigError,
    AgentError,
    DatabaseData,
    ToolContext,
    build_default_registry,
    make_client,
    require_model,
)
from deskpilot.config import get_settings
from deskpilot.storage import create_pool

STATEMENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "statements"


async def main(question: str) -> int:
    settings = get_settings()
    try:
        client = make_client(settings)
        model = require_model(settings)
    except AgentConfigError as error:
        print(error)
        return 2

    try:
        pool = await create_pool(settings.database_url)
    except OSError as error:
        print(f"Cannot reach the database ({error}). Run: make db-up && make migrate")
        await client.close()
        return 2

    try:
        context = ToolContext(
            data=DatabaseData(pool),
            statements_dir=STATEMENTS_DIR,
            clock=lambda: datetime.now(UTC),
        )
        agent = Agent(client, model, build_default_registry(), context)
        try:
            answer = await agent.ask(question)
        except openai.APIStatusError as error:
            print(f"The AI service refused the request (HTTP {error.status_code}): {error.message}")
            return 1
        except openai.APIConnectionError as error:
            print(f"Cannot reach the AI service: {error}")
            return 1
        except AgentError as error:
            print(f"The assistant could not answer: {error}")
            return 1

        for record in answer.tool_calls:
            outcome = f"ERROR: {record.result['error']}" if record.failed else "ok"
            print(f"[tool] {record.name}({record.arguments}) -> {outcome}")
        print()
        print(answer.text)
        return 0
    finally:
        await pool.close()
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the DeskPilot assistant a question.")
    parser.add_argument("question", help="your question, in quotes")
    sys.exit(asyncio.run(main(parser.parse_args().question)))