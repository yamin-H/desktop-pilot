import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from deskpilot.agent import (
    Agent,
    AgentConfigError,
    AgentError,
    build_default_registry,
    make_client,
    require_model,
)
from deskpilot.agent.prompts import system_prompt
from deskpilot.config import Settings


class FakeClient:
    """Looks like the OpenAI async client. Plays back the replies we give it."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))  # the loop keeps changing its messages list
        return self._replies.pop(0)


def say(text):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def call(call_id, name, arguments="{}"):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(id=call_id, type="function", function=function)


def use_tools(*calls, content=None):
    message = SimpleNamespace(content=content, tool_calls=list(calls))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_agent(client, agent_context, **kwargs):
    return Agent(client, "test-model", build_default_registry(), agent_context, **kwargs)


async def test_a_question_that_needs_no_tool_is_answered_directly(agent_context):
    client = FakeClient([say("Hello! I can answer questions about trades and profit.")])
    answer = await make_agent(client, agent_context).ask("hi")
    assert answer.text == "Hello! I can answer questions about trades and profit."
    assert answer.tool_calls == ()
    assert answer.steps == 1


async def test_the_request_carries_the_prompt_the_tools_and_strict_settings(agent_context):
    client = FakeClient([say("ok")])
    await make_agent(client, agent_context).ask("What do we hold?")

    request = client.requests[0]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["tool_choice"] == "auto"
    assert request["tools"] == build_default_registry().schemas()
    system, user = request["messages"]
    assert system["role"] == "system"
    assert "2026-11-12T10:15:00Z" in system["content"]
    assert user == {"role": "user", "content": "What do we hold?"}


async def test_a_tool_result_goes_back_to_the_model_in_the_standard_format(agent_context):
    client = FakeClient(
        [use_tools(call("call_1", "get_positions")), say("We hold 0.3495 BTC and 3 ETH.")]
    )
    answer = await make_agent(client, agent_context).ask("What do we hold?")

    assert answer.text == "We hold 0.3495 BTC and 3 ETH."
    assert answer.steps == 2

    second = client.requests[1]["messages"]
    assert second[2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_positions", "arguments": "{}"},
            }
        ],
    }
    assert second[3]["role"] == "tool"
    assert second[3]["tool_call_id"] == "call_1"
    sent_back = json.loads(second[3]["content"])
    assert sent_back["count"] == 2
    assert sent_back["positions"][0]["quantity"] == "0.3495"

    [record] = answer.tool_calls
    assert (record.name, record.arguments) == ("get_positions", "{}")
    assert record.result == sent_back
    assert record.failed is False


async def test_several_tool_calls_in_one_reply_are_all_answered_in_order(agent_context):
    client = FakeClient(
        [
            use_tools(
                call("a", "get_positions", '{"exchange": "kraken"}'),
                call("b", "get_latest_price", '{"exchange": "binance", "symbol": "BTC/USDT"}'),
            ),
            say("done"),
        ]
    )
    answer = await make_agent(client, agent_context).ask("two things")

    messages = client.requests[1]["messages"]
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == ["a", "b"]
    assert [record.name for record in answer.tool_calls] == ["get_positions", "get_latest_price"]


async def test_a_tool_error_goes_to_the_model_and_does_not_stop_the_loop(agent_context):
    client = FakeClient([use_tools(call("x", "delete_everything")), say("I can't do that.")])
    answer = await make_agent(client, agent_context).ask("delete all trades")

    [record] = answer.tool_calls
    assert record.failed is True
    assert "unknown tool" in record.result["error"]
    tool_message = client.requests[1]["messages"][-1]
    assert "unknown tool" in json.loads(tool_message["content"])["error"]
    assert answer.text == "I can't do that."


async def test_the_model_can_fix_its_own_mistake_after_an_error(agent_context):
    client = FakeClient(
        [
            use_tools(call("1", "get_realized_pnl", '{"start": "yesterday", "end": "today"}')),
            use_tools(
                call("2", "get_realized_pnl", '{"start": "2026-11-10", "end": "2026-11-11"}')
            ),
            say("Realized profit on 2026-11-10 was 1005.23 USDT."),
        ]
    )
    answer = await make_agent(client, agent_context).ask("profit on the 10th?")

    assert [record.failed for record in answer.tool_calls] == [True, False]
    assert "ISO 8601" in answer.tool_calls[0].result["error"]
    assert answer.tool_calls[1].result["totals"][0]["realized_pnl"] == "1005.23"
    assert answer.steps == 3


async def test_a_model_that_never_stops_calling_tools_is_cut_off(agent_context):
    client = FakeClient([use_tools(call(str(i), "get_positions")) for i in range(3)])
    with pytest.raises(AgentError, match="3 requests"):
        await make_agent(client, agent_context, max_steps=3).ask("loop forever")
    assert len(client.requests) == 3


async def test_an_empty_answer_is_an_error(agent_context):
    for empty in ("", "   ", None):
        client = FakeClient([say(empty)])
        with pytest.raises(AgentError, match="empty"):
            await make_agent(client, agent_context).ask("hi")


async def test_an_unsupported_kind_of_tool_call_is_an_error(agent_context):
    custom = SimpleNamespace(id="c", type="custom")  # no .function
    client = FakeClient([use_tools(custom)])
    with pytest.raises(AgentError, match="unsupported"):
        await make_agent(client, agent_context).ask("hi")


def test_the_prompt_states_the_rules_and_the_current_time():
    prompt = system_prompt(datetime(2026, 11, 12, 10, 15, tzinfo=UTC))
    assert "Current time (UTC): 2026-11-12T10:15:00Z" in prompt
    assert "copied from a tool result" in prompt
    assert "read-only" in prompt
    assert "unknown" in prompt


def test_the_client_points_at_groq_with_our_settings():
    settings = Settings(_env_file=None, llm_api_key="gsk_test", llm_model="some-model")
    client = make_client(settings)
    assert str(client.base_url).startswith("https://api.groq.com/openai/v1")
    assert require_model(settings) == "some-model"


def test_a_missing_key_or_model_gets_a_helpful_message():
    with pytest.raises(AgentConfigError, match="LLM_API_KEY"):
        make_client(Settings(_env_file=None, llm_api_key=""))
    with pytest.raises(AgentConfigError, match="LLM_MODEL"):
        require_model(Settings(_env_file=None, llm_model=""))
