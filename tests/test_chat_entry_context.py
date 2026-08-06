from __future__ import annotations


def register_account(client) -> None:
    response = client.post(
        "/auth/register",
        json={
            "account": "advisor-entry-context-user",
            "phone": "13800139901",
            "password": "Advisor-Context-Password-123",
        },
    )
    assert response.status_code == 201


def test_chat_entry_context_is_optional_and_persisted_with_run(client) -> None:
    register_account(client)
    entry_context = {
        "source_page": "stock",
        "module": "research-workspace",
        "as_of": "2026-08-07T10:30:00+08:00",
        "symbol": "000063.SZ",
    }

    response = client.post(
        "/me/chat",
        json={
            "message": "分析中兴通讯当前需要优先核验的风险",
            "symbol": "000063.SZ",
            "execute_agent": False,
            "entry_context": entry_context,
        },
    )

    assert response.status_code == 200
    run = client.get(f"/me/runs/{response.json()['run_id']}")
    assert run.status_code == 200
    assert run.json()["input"]["entry_context"] == entry_context


def test_chat_entry_context_rejects_unknown_nested_fields(client) -> None:
    register_account(client)

    response = client.post(
        "/me/chat",
        json={
            "message": "分析当前风险",
            "entry_context": {
                "source_page": "stock",
                "module": "price-chart",
                "unexpected": True,
            },
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "entry_context", "unexpected"]
    assert detail[0]["type"] == "extra_forbidden"
