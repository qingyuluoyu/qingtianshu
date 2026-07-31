#!/usr/bin/env python3
"""Run one Hermes turn and expose scrubbed text deltas as JSON lines.

The bridge is packaged inside ``app`` so wheel and sdist installations retain
the same streaming path as a source checkout. It runs with the Python runtime
that owns Hermes; the web process never imports Hermes internals directly.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Any


# When this file is executed by absolute path, Python puts ``app/`` at the
# front of ``sys.path``.  That directory also contains ``app/utils.py``, which
# can shadow Hermes' own top-level ``utils`` package and make the streaming
# runtime fail before the first token.  The bridge only needs standard-library
# modules before importing Hermes, so remove its script directory explicitly.
_BRIDGE_DIR = Path(__file__).resolve().parent


def _without_bridge_dir(paths: list[str]) -> list[str]:
    return [
        entry for entry in paths if Path(entry or os.getcwd()).resolve() != _BRIDGE_DIR
    ]


sys.path = _without_bridge_dir(sys.path)


_OUTPUT_LOCK = threading.Lock()
_USAGE_KEYS = (
    "estimated_cost_usd",
    "cost_status",
    "cost_source",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
    "api_calls",
    "model",
    "provider",
    "session_id",
    "completed",
    "failed",
    "partial",
    "service_tier",
    "turn_exit_reason",
)


def emit(event: dict[str, Any], output: Any | None = None) -> None:
    target = output or sys.stdout
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with _OUTPUT_LOCK:
        target.write(payload + "\n")
        target.flush()


def run_bridge(
    prompt: str,
    model: str | None,
    provider: str | None,
    max_tokens: int | None,
    max_iterations: int,
    reasoning_effort: str | None,
    temperature: float | None,
) -> int:
    os.environ["HERMES_SAFE_MODE"] = "1"
    os.environ["HERMES_IGNORE_USER_CONFIG"] = "1"
    os.environ["HERMES_IGNORE_RULES"] = "1"
    os.environ["HERMES_YOLO_MODE"] = "1"
    os.environ["HERMES_ACCEPT_HOOKS"] = "1"
    logging.disable(logging.CRITICAL)

    real_stdout = sys.stdout
    devnull = open(os.devnull, "w", encoding="utf-8")
    try:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            from hermes_cli.config import load_config
            from hermes_cli.fallback_config import get_fallback_chain
            from hermes_cli.oneshot import _oneshot_clarify_callback
            from hermes_cli.runtime_provider import resolve_runtime_provider
            from run_agent import AIAgent

            config = load_config()
            model_config = config.get("model") or {}
            configured_model = (
                model_config
                if isinstance(model_config, str)
                else model_config.get("default") or model_config.get("model") or ""
            )
            effective_model = (model or "").strip() or str(configured_model).strip()
            effective_provider = (provider or "").strip() or None
            runtime = resolve_runtime_provider(
                requested=effective_provider,
                target_model=effective_model or None,
            )
            fallback_chain = get_fallback_chain(config)

            def on_delta(text: str | None) -> None:
                if text is None:
                    emit({"type": "boundary"}, real_stdout)
                elif text:
                    emit({"type": "delta", "text": text}, real_stdout)

            reasoning_config = None
            if reasoning_effort:
                reasoning_config = (
                    {"enabled": False, "effort": "none"}
                    if reasoning_effort == "none"
                    else {"enabled": True, "effort": reasoning_effort}
                )

            agent = AIAgent(
                api_key=runtime.get("api_key"),
                base_url=runtime.get("base_url"),
                provider=runtime.get("provider"),
                api_mode=runtime.get("api_mode"),
                model=effective_model,
                enabled_toolsets=[],
                quiet_mode=True,
                platform="cli",
                credential_pool=runtime.get("credential_pool"),
                fallback_model=fallback_chain or None,
                clarify_callback=_oneshot_clarify_callback,
                max_iterations=max_iterations,
                max_tokens=max_tokens,
                reasoning_config=reasoning_config,
                request_overrides=(
                    {"temperature": temperature} if temperature is not None else None
                ),
                skip_context_files=True,
                skip_memory=True,
                stream_delta_callback=on_delta,
            )
            agent.suppress_status_output = True
            agent.tool_gen_callback = None
            result = agent.run_conversation(prompt)

        answer = str(result.get("final_response") or "").strip()
        if result.get("completed") is False:
            emit(
                {
                    "type": "error",
                    "error": "Hermes did not complete the answer within its turn budget",
                },
                real_stdout,
            )
            return 1
        if not answer:
            emit(
                {
                    "type": "error",
                    "error": str(result.get("error") or "Hermes did not return text"),
                },
                real_stdout,
            )
            return 1
        emit(
            {
                "type": "final",
                "answer": answer,
                "usage": {key: result.get(key) for key in _USAGE_KEYS},
            },
            real_stdout,
        )
        return 0
    except BaseException as exc:  # noqa: BLE001 - bridge must report cleanly
        emit(
            {"type": "error", "error": f"{type(exc).__name__}: {exc}"},
            real_stdout,
        )
        return 1
    finally:
        devnull.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--provider")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "max"),
    )
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        emit({"type": "delta", "text": "真实"})
        emit({"type": "delta", "text": "流式"})
        emit({"type": "boundary"})
        emit(
            {
                "type": "final",
                "answer": "真实流式",
                "usage": {"completed": True, "api_calls": 0},
            }
        )
        return 0
    if args.prompt_file is None:
        parser.error("--prompt-file is required unless --self-test is used")
    prompt = args.prompt_file.read_text(encoding="utf-8")
    if args.max_tokens is not None and args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if args.max_iterations <= 0:
        parser.error("--max-iterations must be positive")
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        parser.error("--temperature must be between 0 and 2")
    return run_bridge(
        prompt,
        args.model,
        args.provider,
        args.max_tokens,
        args.max_iterations,
        args.reasoning_effort,
        args.temperature,
    )


if __name__ == "__main__":
    raise SystemExit(main())
