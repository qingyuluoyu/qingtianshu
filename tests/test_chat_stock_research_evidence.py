from __future__ import annotations

from app.providers.market import ProviderError


def register_account(client) -> None:
    response = client.post(
        "/auth/register",
        json={
            "account": "advisor-provider-degrade-user",
            "phone": "13800139903",
            "password": "Advisor-Provider-Degrade-Password-123",
        },
    )
    assert response.status_code == 201


def test_online_stock_provider_failure_keeps_chat_run_and_context(
    client, app, monkeypatch
) -> None:
    register_account(client)

    def fail_online_evidence(*args, **kwargs):
        del args, kwargs
        raise ProviderError("synthetic Yahoo timeout")

    monkeypatch.setattr(app.state.research_evidence, "build", fail_online_evidence)
    entry_context = {
        "source_page": "stock",
        "module": "stock-research",
        "symbol": "000063.SZ",
    }
    response = client.post(
        "/me/chat",
        json={
            "message": "分析中兴通讯当前最需要优先核验的风险",
            "symbol": "000063.SZ",
            "execute_agent": False,
            "entry_context": entry_context,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "preview"
    assert "行情暂不可用" in payload["answer"]
    assert "下一步仍需补充" in payload["answer"]
    assert "—%" not in payload["answer"]
    assert "当前价格证据" not in payload["answer"]
    assert "不能给出可信的风险优先级" in payload["answer"]
    assert payload["evidence"]["evidence_status"] == "partial"
    assert payload["evidence"]["warnings"] == [
        "外部行情或公司证据刷新暂时未完成；本轮不会补写价格、涨跌、财务或事件事实。"
    ]

    run = client.get(f"/me/runs/{payload['run_id']}")
    assert run.status_code == 200
    assert run.json()["input"]["entry_context"] == {
        **entry_context,
        "as_of": None,
    }

    conversation = client.get(f"/me/conversations/{payload['conversation_id']}")
    assert conversation.status_code == 200
    assert conversation.json()["messages"][-1]["content"] == payload["answer"]
