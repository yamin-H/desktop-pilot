import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field

from deskpilot.agent.data import StaticData
from deskpilot.agent.tools.registry import Tool, ToolArgs, ToolContext, ToolError, ToolRegistry
from deskpilot.analytics import OversoldError

NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)


class EchoArgs(ToolArgs):
    text: str = Field(description="Text to echo back.")
    mode: Literal["loud", "quiet"] | None = Field(None, description="How to echo.")
    times: int = Field(1, ge=1, le=5, description="How many times.")


class NoArgs(ToolArgs):
    pass


async def echo(context, args):
    return {"echo": [args.text] * args.times, "mode": args.mode}


async def ping(context, args):
    return {"ok": True}


async def explain_problem(context, args):
    raise ToolError("that went wrong, on purpose")


async def ledger_problem(context, args):
    raise OversoldError("sold more than held")


async def crash(context, args):
    raise RuntimeError("secret internal detail")


REGISTRY = ToolRegistry(
    [
        Tool("echo", "Echo text back.", EchoArgs, echo),
        Tool("ping", "Do nothing.", NoArgs, ping),
        Tool("explain_problem", "Fail with an explainable error.", NoArgs, explain_problem),
        Tool("ledger_problem", "Fail like the ledger does.", NoArgs, ledger_problem),
        Tool("crash", "Fail with a bug.", NoArgs, crash),
    ]
)
CONTEXT = ToolContext(data=StaticData(), statements_dir=Path("."), clock=lambda: NOW)


async def call(name, arguments=None):
    raw = json.dumps(arguments) if isinstance(arguments, dict) else arguments
    return await REGISTRY.call(name, raw, CONTEXT)


def test_the_schema_is_in_openai_function_format():
    schema = REGISTRY.schemas()[0]
    assert schema["type"] == "function"
    function = schema["function"]
    assert (function["name"], function["description"]) == ("echo", "Echo text back.")
    parameters = function["parameters"]
    assert parameters["type"] == "object"
    assert parameters["required"] == ["text"]
    assert parameters["additionalProperties"] is False
    assert set(parameters["properties"]) == {"text", "mode", "times"}
    assert parameters["properties"]["mode"]["enum"] == ["loud", "quiet"]
    assert parameters["properties"]["times"]["minimum"] == 1
    assert parameters["properties"]["times"]["maximum"] == 5
    assert parameters["properties"]["text"]["description"] == "Text to echo back."


def test_the_schema_is_kept_plain_for_every_provider():
    text = json.dumps(REGISTRY.schemas())
    for unwanted in ("anyOf", '"title"', "$defs", "$ref", '"null"'):
        assert unwanted not in text


def test_the_tool_names_are_listed():
    assert REGISTRY.names == ["echo", "ping", "explain_problem", "ledger_problem", "crash"]


def test_duplicate_tool_names_are_refused():
    with pytest.raises(ValueError, match="unique"):
        ToolRegistry([Tool("a", "x", NoArgs, ping), Tool("a", "y", NoArgs, ping)])


async def test_a_tool_runs_with_valid_arguments():
    assert await call("echo", {"text": "hi", "times": 2}) == {"echo": ["hi", "hi"], "mode": None}


async def test_null_is_accepted_for_optional_arguments():
    assert (await call("echo", {"text": "hi", "mode": None}))["mode"] is None


@pytest.mark.parametrize("raw", [None, "", "   ", "{}"])
async def test_a_tool_without_arguments_accepts_any_empty_form(raw):
    assert await call("ping", raw) == {"ok": True}


async def test_an_unknown_tool_is_an_error_that_lists_the_real_ones():
    result = await call("delete_everything")
    assert "unknown tool" in result["error"]
    assert "echo" in result["error"]


async def test_arguments_that_are_not_json_are_an_error():
    assert "not valid JSON" in (await call("echo", "{oops"))["error"]


async def test_arguments_that_are_not_an_object_are_an_error():
    assert "JSON object" in (await call("echo", "[1, 2]"))["error"]


async def test_a_missing_required_argument_is_named():
    assert "text" in (await call("echo", {}))["error"]


async def test_an_invented_argument_is_refused():
    result = await call("echo", {"text": "hi", "colour": "red"})
    assert "colour" in result["error"]
    assert "not permitted" in result["error"]


async def test_a_value_out_of_range_is_named():
    assert "times" in (await call("echo", {"text": "hi", "times": 9}))["error"]


async def test_a_wrong_choice_lists_the_allowed_ones():
    result = await call("echo", {"text": "hi", "mode": "whisper"})
    assert "loud" in result["error"]
    assert "quiet" in result["error"]


def test_optional_arguments_may_be_null_in_the_schema():
    mode = REGISTRY.schemas()[0]["function"]["parameters"]["properties"]["mode"]
    assert mode["type"] == ["string", "null"]


async def test_an_explainable_problem_is_passed_on_as_an_error():
    assert await call("explain_problem") == {"error": "that went wrong, on purpose"}


async def test_a_ledger_problem_is_explained():
    result = await call("ledger_problem")
    assert "ledger" in result["error"]
    assert "sold more than held" in result["error"]


async def test_a_bug_is_logged_in_full_but_hidden_from_the_model(caplog):
    with caplog.at_level(logging.ERROR):
        result = await call("crash")
    assert "internal error in tool crash" in result["error"]
    assert "Do not guess" in result["error"]
    assert "secret internal detail" not in result["error"]
    assert "secret internal detail" in caplog.text  # the traceback is in our log
