from __future__ import annotations

from pathlib import Path

import app.services.agent as agent_module
from app.services.agent import AgentService


def test_agent_service_delegates_preview_rendering(monkeypatch) -> None:
    evidence = {"type": "general_research"}
    captured = {}

    def fake_render(value, *, render_li_zong_preview):
        captured["evidence"] = value
        captured["li_zong_renderer"] = render_li_zong_preview
        return "delegated preview"

    monkeypatch.setattr(agent_module, "render_preview", fake_render)

    assert AgentService._render_preview(evidence) == "delegated preview"
    assert captured["evidence"] is evidence
    assert callable(captured["li_zong_renderer"])


def test_preview_modules_do_not_import_agent_service() -> None:
    services = Path(__file__).resolve().parents[1] / "app" / "services"

    for path in services.glob("agent_preview*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.services.agent import" not in source, path.name
        assert "AgentService." not in source, path.name


def test_preview_dispatcher_stays_thin() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "agent_preview.py"
    )

    assert len(path.read_text(encoding="utf-8").splitlines()) <= 60
