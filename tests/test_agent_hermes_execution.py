from __future__ import annotations

from pathlib import Path

import app.services.agent as agent_module
from app.db import Database
from app.services.agent import AgentService
from app.services.agent_hermes_execution import GuardedStreamCallbacks


def test_agent_service_delegates_oneshot_transport(
    tmp_path: Path, settings, monkeypatch
) -> None:
    service = AgentService(Database(tmp_path / "db"), settings)
    captured = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return "本轮新回答", {"model": "test"}

    monkeypatch.setattr(agent_module, "execute_hermes_oneshot", fake_execute)

    result = service._execute_hermes(
        prompt="测试问题",
        model_tier="economy",
        run_dir=tmp_path,
        user_workspace=tmp_path,
        image_path=None,
    )

    assert result == ("本轮新回答", {"model": "test"})
    assert captured["settings"] is settings
    assert captured["prompt"] == "测试问题"
    assert captured["extract_chat_answer"] is service._extract_chat_answer


def test_agent_service_injects_financial_guards_into_stream_transport(
    tmp_path: Path, settings, monkeypatch
) -> None:
    service = AgentService(Database(tmp_path / "db"), settings)
    captured = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return "最终回答", {"streaming": {"enabled": True}}

    monkeypatch.setattr(agent_module, "execute_hermes_streaming", fake_execute)
    updates = []
    evidence = {"type": "market_brief"}

    result = service._execute_hermes_streaming(
        model_tier="economy",
        run_dir=tmp_path,
        user_workspace=tmp_path,
        evidence=evidence,
        trusted_context=["已确认上下文"],
        stream_callback=updates.append,
    )

    assert result == ("最终回答", {"streaming": {"enabled": True}})
    assert captured["evidence"] is evidence
    assert captured["trusted_context"] == ["已确认上下文"]
    assert captured["stream_callback"].__self__ is updates
    callbacks = captured["callbacks"]
    assert isinstance(callbacks, GuardedStreamCallbacks)
    assert callbacks.validate_output is AgentService._validate_model_output
    assert (
        callbacks.partial_has_blocker
        is AgentService._stream_partial_guard_has_blocker
    )
