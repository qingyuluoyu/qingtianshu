from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_orchestration_does_not_import_main() -> None:
    source = (
        ROOT / "app" / "services" / "chat_orchestration.py"
    ).read_text(encoding="utf-8")

    assert "from app.main import" not in source
    assert "import app.main" not in source


def test_chat_routes_remain_thin_adapters() -> None:
    tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    route_lengths = {
        node.name: node.end_lineno - node.lineno + 1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"chat", "my_chat", "refine_my_chat"}
    }

    assert route_lengths == {"chat": 3, "my_chat": 3, "refine_my_chat": 3}
