import json
import logging
from dataclasses import dataclass
from typing import Any
import openai
from deskpilot.agent.prompts import system_prompt
from deskpilot.agent.tools import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """The assistant could not produce an answer."""


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool the model asked for, and what it got back."""

    name: str
    arguments: str  # exactly as the model sent it
    result: dict[str, Any]

    @property
    def failed(self) -> bool:
        return "error" in self.result


@dataclass(frozen=True)
class Answer:
    text: str
    tool_calls: tuple[ToolCallRecord, ...]
    steps: int  # how many times the model was asked


class Agent:
    """Ask a question; the model may call tools; return the final answer.

    `client` is anything shaped like the OpenAI SDK's async client, so a fake works in tests.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        registry: ToolRegistry,
        context: ToolContext,
        *,
        max_steps: int = 6,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._model = model
        self._registry = registry
        self._context = context
        self._max_steps = max_steps
        self._temperature = temperature

    async def ask(self, question: str) -> Answer:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(self._context.clock())},
            {"role": "user", "content": question},
        ]
        records: list[ToolCallRecord] = []

        for step in range(1, self._max_steps + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._registry.schemas(),
                    tool_choice="auto",
                    temperature=self._temperature,
                )
            except openai.BadRequestError as error:
                if getattr(error, "code", "") != "tool_use_failed":
                    raise
                logger.warning("tool call rejected (tool_use_failed); retrying without tools")
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tool_choice="none",
                    temperature=self._temperature,
                )
            message = response.choices[0].message
            requested = list(message.tool_calls or [])

            if not requested:
                text = (message.content or "").strip()
                if not text:
                    raise AgentError("the model returned an empty answer")
                return Answer(text=text, tool_calls=tuple(records), steps=step)

            calls = [call for call in requested if getattr(call, "function", None) is not None]
            if len(calls) != len(requested):
                raise AgentError("the model asked for an unsupported kind of tool call")

            # Send back exactly what the model asked for, in the standard format.
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                result = await self._registry.call(
                    call.function.name, call.function.arguments, self._context
                )
                records.append(ToolCallRecord(call.function.name, call.function.arguments, result))
                logger.info(
                    "tool %s -> %s", call.function.name, "error" if "error" in result else "ok"
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        raise AgentError(f"no final answer after {self._max_steps} requests to the model")
