from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable

from app.config import Settings
from app.hermes_runtime import (
    resolve_hermes_executable,
    resolve_hermes_python,
    resolve_hermes_stream_bridge,
)


def resolve_hermes_route(model_tier: str) -> tuple[str | None, str | None]:
    """Resolve the product model route without depending on Hermes globals."""

    provider = os.getenv(f"HERMES_{model_tier.upper()}_PROVIDER") or None
    model = os.getenv(f"HERMES_{model_tier.upper()}_MODEL") or None
    if model_tier in {"economy", "deep"}:
        provider = provider or "custom"
        model = model or "step-3.7-flash"
    return provider, model


def hermes_max_tokens(intent: str, model_tier: str) -> int:
    """Bound answer length while keeping the configured Hermes model."""

    override = str(os.getenv(f"HERMES_{model_tier.upper()}_MAX_TOKENS") or "").strip()
    if override:
        try:
            return max(256, min(int(override), 8192))
        except ValueError:
            pass

    if model_tier == "deep":
        return 2200
    return {
        "market_brief": 900,
        "stock_research": 1200,
        "stock_comparison": 1200,
        "stock_screen": 1000,
        "watchlist_brief": 1200,
        "watchlist_update": 900,
        "market_pulse_article": 1600,
        "trade_review": 1800,
        "visual_research": 1800,
    }.get(intent, 1100)


def hermes_reasoning_effort(
    model_tier: str, intent: str = "", research_focus: str = ""
) -> str:
    """Choose a latency-conscious reasoning level for the same text model."""

    override = (
        str(os.getenv(f"HERMES_{model_tier.upper()}_REASONING_EFFORT") or "")
        .strip()
        .lower()
    )
    if override in {"none", "low", "medium", "high", "max"}:
        return override
    if model_tier == "economy" and research_focus == "quality_review":
        return "low"
    if model_tier == "economy" and intent in {
        "stock_research",
        "market_brief",
        "earnings_quality",
        "financial_drivers",
        "business_structure",
        "shareholder_structure",
        "analyst_expectations",
        "event_timeline",
    }:
        return "none"
    return "medium" if model_tier == "deep" else "low"


def hermes_max_iterations(model_tier: str) -> int:
    """Give a toolless Hermes turn enough room to produce a final response."""

    override = str(
        os.getenv(f"HERMES_{model_tier.upper()}_MAX_ITERATIONS") or ""
    ).strip()
    if override:
        try:
            return max(2, min(int(override), 12))
        except ValueError:
            pass
    return 6 if model_tier == "deep" else 4


def hermes_temperature(model_tier: str, evidence: dict[str, Any]) -> float | None:
    """Use steadier sampling for evidence-dense financial conversations."""

    override = str(os.getenv(f"HERMES_{model_tier.upper()}_TEMPERATURE") or "").strip()
    if override:
        try:
            return max(0.0, min(float(override), 2.0))
        except ValueError:
            pass

    research_plan = evidence.get("research_plan") or {}
    if (
        model_tier == "economy"
        and str(evidence.get("type") or "") == "stock_research"
        and str(research_plan.get("focus") or "") == "quality_review"
    ):
        return 0.3
    return None


@dataclass(frozen=True)
class GuardedStreamCallbacks:
    """Financial-output policy hooks owned by ``AgentService``.

    The Hermes transport knows how to run and stream a model, while the Agent
    keeps ownership of financial validation and public-language policy. This
    explicit boundary avoids importing the large Agent module into the runtime.
    """

    clean_user_facing: Callable[[str], str]
    validate_output: Callable[..., dict[str, Any]]
    partial_has_blocker: Callable[[dict[str, Any]], bool]
    waits_for_required_context: Callable[[dict[str, Any]], bool]
    guard_text: Callable[[list[str]], str]
    take_complete_segments: Callable[[str], tuple[list[str], str]]


def execute_hermes_oneshot(
    *,
    settings: Settings,
    prompt: str,
    model_tier: str,
    run_dir: Path,
    user_workspace: Path,
    image_path: str | None,
    extract_chat_answer: Callable[[str], str],
) -> tuple[str, dict[str, Any] | None]:
    hermes_bin = resolve_hermes_executable(settings.hermes_bin)
    provider, model = resolve_hermes_route(model_tier)
    usage_path = run_dir / "usage.json"

    if image_path:
        image = Path(image_path).expanduser().resolve()
        try:
            image.relative_to(user_workspace.resolve())
        except ValueError as exc:
            raise ValueError("图片必须位于当前用户的专属工作区中") from exc
        command = [
            str(hermes_bin),
            "chat",
            "-q",
            prompt,
            "--image",
            str(image),
            "-Q",
            "--safe-mode",
            "--max-turns",
            "1",
            "--source",
            "tool",
        ]
    else:
        command = [
            str(hermes_bin),
            "-z",
            prompt,
            "--usage-file",
            str(usage_path),
            "--safe-mode",
            "--toolsets",
            "context_engine",
        ]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["-m", model])

    # A Windows service or hidden background process can have no inherited
    # console streams. Capture through temporary files so Hermes output remains
    # available even when PIPE-based capture would produce ``stdout=None``.
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file,
    ):
        result = subprocess.run(
            command,
            cwd=user_workspace,
            text=True,
            stdout=stdout_file,
            stderr=stderr_file,
            timeout=settings.hermes_timeout_seconds,
            check=False,
        )
        stdout_file.seek(0)
        captured_stdout = stdout_file.read()
    if result.returncode != 0:
        raise RuntimeError(f"Hermes 退出码 {result.returncode}")
    raw_answer = (
        result.stdout if isinstance(result.stdout, str) else captured_stdout
    ).strip()
    answer = extract_chat_answer(raw_answer) if image_path else raw_answer
    if not answer:
        raise RuntimeError("Hermes 未返回文本")

    usage = None
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            usage = {"warning": "Hermes usage 文件无法解析"}
    return answer, usage


def execute_hermes_streaming(
    *,
    settings: Settings,
    model_tier: str,
    run_dir: Path,
    user_workspace: Path,
    evidence: dict[str, Any],
    trusted_context: list[str] | None,
    stream_callback: Callable[[dict[str, Any]], None],
    callbacks: GuardedStreamCallbacks,
    required_context_prefix: str | None = None,
    prompt_path: Path | None = None,
) -> tuple[str, dict[str, Any] | None]:
    hermes_bin = resolve_hermes_executable(settings.hermes_bin)
    python_bin = resolve_hermes_python(hermes_bin)
    bridge = resolve_hermes_stream_bridge()

    provider, model = resolve_hermes_route(model_tier)
    intent = str(evidence.get("type") or "")
    max_tokens = hermes_max_tokens(intent, model_tier)
    max_iterations = hermes_max_iterations(model_tier)
    research_focus = str((evidence.get("research_plan") or {}).get("focus") or "")
    reasoning_effort = hermes_reasoning_effort(model_tier, intent, research_focus)
    temperature = hermes_temperature(model_tier, evidence)
    command = [
        str(python_bin),
        str(bridge),
        "--prompt-file",
        str(prompt_path or (run_dir / "prompt.md")),
        "--max-tokens",
        str(max_tokens),
        "--max-iterations",
        str(max_iterations),
        "--reasoning-effort",
        reasoning_effort,
    ]
    if temperature is not None:
        command.extend(["--temperature", str(temperature)])
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])

    process = subprocess.Popen(  # noqa: S603 - fixed local runtime and script
        command,
        cwd=user_workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RuntimeError("Hermes streaming bridge pipes were not created")

    events: Queue[str | None] = Queue()

    def read_stdout() -> None:
        try:
            for line in process.stdout:
                events.put(line)
        finally:
            events.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    started = time.perf_counter()
    deadline = started + settings.hermes_timeout_seconds
    raw_pending = ""
    safe_segments: list[str] = []
    visible_start_index: int | None = None
    required_context_deferred = False
    required_context_prefix_injected = False
    last_visible_draft = ""
    first_token_seconds: float | None = None
    first_visible_seconds: float | None = None
    delta_events = 0
    visible_events = 0
    withheld_segments = 0
    deferred_segments = 0
    final_event: dict[str, Any] | None = None
    bridge_error: str | None = None

    def streaming_usage(
        *, partial: bool = False, reason: str | None = None
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "enabled": True,
            "mode": "guarded_cumulative_stream_v3",
            "max_tokens": max_tokens,
            "max_iterations": max_iterations,
            "reasoning_effort": reasoning_effort,
            "temperature": temperature,
            "first_token_seconds": (
                round(first_token_seconds, 3)
                if first_token_seconds is not None
                else None
            ),
            "first_visible_seconds": (
                round(first_visible_seconds, 3)
                if first_visible_seconds is not None
                else None
            ),
            "raw_delta_events": delta_events,
            "visible_events": visible_events,
            "visible_characters": len(last_visible_draft),
            "withheld_segments": withheld_segments,
            "deferred_segments": deferred_segments,
            "required_context_prefix_injected": required_context_prefix_injected,
        }
        if partial:
            metadata["transport_recovery"] = "guarded_partial"
            metadata["partial_reason"] = reason
        return metadata

    try:
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError("Hermes streaming bridge timed out")
            try:
                line = events.get(timeout=min(0.2, remaining))
            except Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Hermes streaming bridge emitted invalid JSON"
                ) from exc
            event_type = event.get("type")
            if event_type == "delta":
                text = str(event.get("text") or "")
                if not text:
                    continue
                delta_events += 1
                if first_token_seconds is None:
                    first_token_seconds = time.perf_counter() - started
                raw_pending += text
                complete, raw_pending = callbacks.take_complete_segments(raw_pending)
                for segment in complete:
                    cleaned = callbacks.clean_user_facing(segment)
                    if not cleaned:
                        continue
                    segment_guard = callbacks.validate_output(
                        cleaned,
                        evidence,
                        trusted_context=trusted_context,
                    )
                    if callbacks.partial_has_blocker(segment_guard):
                        withheld_segments += 1
                        continue
                    candidate_segments = [*safe_segments, segment]
                    candidate_guard_text = callbacks.guard_text(candidate_segments)
                    partial_guard = callbacks.validate_output(
                        candidate_guard_text,
                        evidence,
                        trusted_context=trusted_context,
                    )
                    if callbacks.partial_has_blocker(partial_guard):
                        withheld_segments += 1
                        continue
                    safe_segments = candidate_segments
                    if callbacks.waits_for_required_context(partial_guard):
                        deferred_segments += 1
                        required_context_deferred = True
                        continue
                if safe_segments:
                    visible_guard = callbacks.validate_output(
                        callbacks.guard_text(safe_segments),
                        evidence,
                        trusted_context=trusted_context,
                    )
                    if callbacks.waits_for_required_context(visible_guard):
                        required_context_deferred = True
                        if (
                            required_context_prefix
                            and not required_context_prefix_injected
                            and len(safe_segments) >= 2
                        ):
                            safe_segments.insert(0, required_context_prefix)
                            required_context_prefix_injected = True
                            required_context_deferred = False
                            visible_guard = callbacks.validate_output(
                                callbacks.guard_text(safe_segments),
                                evidence,
                                trusted_context=trusted_context,
                            )
                            if callbacks.waits_for_required_context(visible_guard):
                                continue
                        else:
                            continue
                if visible_start_index is None:
                    visible_start_index = 0
                    if required_context_deferred:
                        for index in range(len(safe_segments) - 1, -1, -1):
                            suffix_guard = callbacks.validate_output(
                                callbacks.guard_text(safe_segments[index:]),
                                evidence,
                                trusted_context=trusted_context,
                            )
                            if not callbacks.waits_for_required_context(suffix_guard):
                                visible_start_index = index
                                break
                visible_draft = callbacks.clean_user_facing(
                    "".join(safe_segments[visible_start_index:])
                )
                if visible_draft and visible_draft != last_visible_draft:
                    visible_events += 1
                    if first_visible_seconds is None:
                        first_visible_seconds = time.perf_counter() - started
                    last_visible_draft = visible_draft
                    stream_callback(
                        {
                            "type": "delta",
                            "draft": visible_draft,
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "event_index": visible_events,
                            "withheld_segments": withheld_segments,
                            "is_unverified": True,
                            "is_guarded_partial": True,
                        }
                    )
            elif event_type == "final":
                final_event = event
            elif event_type == "error":
                bridge_error = str(event.get("error") or "Hermes bridge failed")
        try:
            return_code = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.terminate()
            return_code = process.wait(timeout=2)
        stderr = process.stderr.read().strip()
        if bridge_error:
            raise RuntimeError(bridge_error)
        if return_code != 0:
            raise RuntimeError(
                f"Hermes streaming bridge exited with {return_code}: {stderr[:240]}"
            )
        if final_event is None or not str(final_event.get("answer") or "").strip():
            raise RuntimeError("Hermes streaming bridge returned no final answer")
    except Exception as exc:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        partial_answer = last_visible_draft.strip()
        sentence_count = sum(partial_answer.count(mark) for mark in "。！？")
        if len(partial_answer) >= 160 and sentence_count >= 2:
            return partial_answer, {
                "completed": False,
                "failed": False,
                "partial": True,
                "turn_exit_reason": "guarded_partial_after_transport_failure",
                "streaming": streaming_usage(
                    partial=True,
                    reason=type(exc).__name__,
                ),
            }
        raise

    usage = dict(final_event.get("usage") or {})
    usage["streaming"] = streaming_usage()
    return str(final_event["answer"]).strip(), usage
