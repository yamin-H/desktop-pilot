import asyncio
import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from deskpilot.agent import Agent, AgentError, ToolCallRecord
from deskpilot.evals.golden import GoldenQuestion
from deskpilot.evals.scoring import Check, score_answer

CHECK_ORDER = ("tools", "numbers", "grounding", "mentions", "says")
CHECK_LABELS = {
    "tools": "Tool-call accuracy",
    "numbers": "Numeric correctness",
    "grounding": "No invented numbers",
    "mentions": "Names the right trades and items",
    "says": "Right kind of reply (refusal, not found, ...)",
}


@dataclass(frozen=True)
class RunResult:
    question: GoldenQuestion
    attempt: int
    answer: str | None
    records: tuple[ToolCallRecord, ...]
    checks: tuple[Check, ...]
    error: str | None  # the model or service failed, so there was nothing to score
    seconds: float
    steps: int

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)


@dataclass(frozen=True)
class Ratio:
    ok: int
    total: int

    @property
    def percent(self) -> float:
        return 100.0 * self.ok / self.total if self.total else 0.0

    def __str__(self) -> str:
        return f"{self.ok}/{self.total} ({self.percent:.1f}%)"


@dataclass(frozen=True)
class Summary:
    runs: int
    passed: int
    errors: int
    checks: dict[str, Ratio]  # only runs that produced an answer are counted here


async def run_evaluation(
    agent: Agent,
    questions: Sequence[GoldenQuestion],
    *,
    repeat: int = 1,
    delay: float = 0.0,
    extra_numbers: Iterable[Decimal] = (),
    provider_errors: tuple[type[BaseException], ...] = (),
    on_result: Callable[[RunResult], None] | None = None,
) -> list[RunResult]:
    """Ask every question `repeat` times and score the answers.

    `provider_errors` are failures of the AI service itself (rate limits, outages): they are
    recorded as errors and the run continues. Any other exception is a bug and is raised.
    """
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    extra = tuple(extra_numbers)
    expected_errors = (AgentError, *provider_errors)

    results: list[RunResult] = []
    first = True
    for question in questions:
        for attempt in range(1, repeat + 1):
            if delay and not first:
                await asyncio.sleep(delay)
            first = False

            started = time.perf_counter()
            try:
                answer = await agent.ask(question.question)
            except expected_errors as error:
                result = RunResult(
                    question, attempt, None, (), (),
                    f"{type(error).__name__}: {error}", time.perf_counter() - started, 0,
                )
            else:
                checks = score_answer(
                    question, answer.text, answer.tool_calls, extra_numbers=extra
                )
                result = RunResult(
                    question, attempt, answer.text, answer.tool_calls, tuple(checks),
                    None, time.perf_counter() - started, answer.steps,
                )
            results.append(result)
            if on_result is not None:
                on_result(result)
    return results


def summarize(results: Sequence[RunResult]) -> Summary:
    counts: dict[str, list[int]] = {}
    for result in results:
        if result.error is not None:
            continue
        for check in result.checks:
            ok_and_total = counts.setdefault(check.name, [0, 0])
            ok_and_total[0] += check.passed
            ok_and_total[1] += 1
    return Summary(
        runs=len(results),
        passed=sum(result.passed for result in results),
        errors=sum(result.error is not None for result in results),
        checks={name: Ratio(*counts[name]) for name in CHECK_ORDER if name in counts},
    )


def _problems(run: RunResult) -> str:
    if run.error is not None:
        return run.error
    return "; ".join(f"{c.name}: {c.detail}" for c in run.checks if not c.passed)


def _by_question(results: Sequence[RunResult]) -> dict[str, list[RunResult]]:
    grouped: dict[str, list[RunResult]] = {}
    for result in results:
        grouped.setdefault(result.question.id, []).append(result)
    return grouped


def format_report(results: Sequence[RunResult], *, model: str = "") -> str:
    """A plain-text report: one line per question, then the summary."""
    grouped = _by_question(results)
    width = max((len(name) for name in grouped), default=8) + 2
    lines = [f"{'question':<{width}}{'result':<8}notes"]
    for name, runs in grouped.items():
        passed = sum(run.passed for run in runs)
        label = ("PASS" if passed == len(runs) else "FAIL") if len(runs) == 1 else f"{passed}/{len(runs)}"
        failing = next((run for run in runs if not run.passed), None)
        notes = _problems(failing) if failing else ""
        if len(notes) > 150:
            notes = notes[:147] + "..."
        lines.append(f"{name:<{width}}{label:<8}{notes}")

    summary = summarize(results)
    percent = 100.0 * summary.passed / summary.runs if summary.runs else 0.0
    lines += [
        "",
        f"SUMMARY{f' ({model})' if model else ''}",
        f"  runs: {summary.runs}   passed: {summary.passed} ({percent:.1f}%)   "
        f"errors (no answer): {summary.errors}",
    ]
    for name, ratio in summary.checks.items():
        lines.append(f"  {CHECK_LABELS[name]:<48}{ratio}")
    return "\n".join(lines)


def format_markdown(results: Sequence[RunResult], *, model: str) -> str:
    """A small table you can paste into the README."""
    summary = summarize(results)
    failed = [name for name, runs in _by_question(results).items() if not all(r.passed for r in runs)]
    lines = [
        f"**Model:** `{model}`  ",
        f"**Runs:** {summary.runs}, fully passed: {summary.passed}, no answer: {summary.errors}",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for name, ratio in summary.checks.items():
        lines.append(f"| {CHECK_LABELS[name]} | {ratio} |")
    lines += ["", f"Failed: {', '.join(failed) if failed else 'none'}"]
    return "\n".join(lines)


def write_transcript(results: Sequence[RunResult], path: Path) -> None:
    """Save everything (answers, tool calls, scores) as one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for run in results:
            row = {
                "id": run.question.id,
                "attempt": run.attempt,
                "question": run.question.question,
                "answer": run.answer,
                "error": run.error,
                "passed": run.passed,
                "seconds": round(run.seconds, 2),
                "steps": run.steps,
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail} for c in run.checks
                ],
                "tool_calls": [
                    {"name": r.name, "arguments": r.arguments, "result": r.result}
                    for r in run.records
                ],
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")