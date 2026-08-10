from __future__ import annotations


def test_knowledge_upload_persists_explicit_multipart_title(client):
    registered = client.post(
        "/auth/register",
        json={
            "account": "knowledge-contract-user",
            "phone": "13800138000",
            "password": "Knowledge-Contract-123",
        },
    )
    assert registered.status_code == 201

    uploaded = client.post(
        "/me/knowledge",
        data={"title": "自定义研究标题"},
        files={"file": ("note.md", "# 原始标题\n内容".encode("utf-8"), "text/markdown")},
    )

    assert uploaded.status_code == 201
    assert uploaded.json()["title"] == "自定义研究标题"
