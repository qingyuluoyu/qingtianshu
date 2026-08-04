# 金融顾问测试台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同一个 FastAPI 端口提供独立、只读、可回放的金融顾问测试台，并让每条回答展示脱敏后的真实上下文快照。

**Architecture:** 复用现有聊天上下文、编排与 Agent 服务。`conversation_mode=advisor_test` 与正式会话隔离；上下文快照仅以白名单助手消息元数据存储；测试端由服务端只读策略阻断业务写入。

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL, Pydantic, 静态 HTML/CSS/JavaScript, pytest。

## Global Constraints

- 页面、API 和 SSE 使用同一个 FastAPI 端口，入口是 `/advisor-lab`。
- 复用正式聊天链路，不另建提示词、检索或金融计算。
- 旧会话默认 `formal`；测试会话为 `advisor_test`。
- API 层拒绝写操作，快照不得含 prompt、密钥、内部路径或其他用户数据。

---

### Task 1: 会话隔离迁移

**Files:**

- Modify: `app/domain_schema.py`, `app/db.py`, `app/api_models.py`, `app/services/chat_context.py`, `app/main.py`
- Test: `tests/test_advisor_lab.py`

**Interfaces:**

- `Database.create_conversation(..., conversation_mode: str = "formal")`
- `Database.list_conversations(..., conversation_mode: str | None = None)`
- `ChatRequestContextService.prepare(..., conversation_mode: str = "formal")`

- [ ] **Step 1: Write the failing isolation test**

```python
def test_advisor_lab_conversation_is_not_returned_by_formal_history(client):
    create_user(client, "Advisor Lab User")
    response = client.post("/me/advisor-lab/chat", json={"message": "今天 A 股怎么样？", "execute_agent": False})
    assert response.status_code == 200
    assert client.get("/me/conversations").json()["items"] == []
    assert client.get("/me/advisor-lab/conversations").json()["items"][0]["conversation_mode"] == "advisor_test"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_advisor_lab.py::test_advisor_lab_conversation_is_not_returned_by_formal_history -q`

Expected: endpoint 404 before implementation.

- [ ] **Step 3: Implement the expand migration**

```python
VALID_CONVERSATION_MODES = {"formal", "advisor_test"}
Database._ensure_column(connection, "conversations", "conversation_mode", "TEXT NOT NULL DEFAULT 'formal'")
```

Add the default to `DOMAIN_SCHEMA_SQL`, increment `SCHEMA_VERSION`, validate modes, pass the desired mode when creating a conversation, and reject an existing conversation whose mode differs. Formal endpoints explicitly query `formal` only.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_advisor_lab.py::test_advisor_lab_conversation_is_not_returned_by_formal_history tests/test_domain_schema.py -q`

- [ ] **Step 5: Commit**

Run: `git add app/domain_schema.py app/db.py app/api_models.py app/services/chat_context.py app/main.py tests/test_advisor_lab.py && git commit -m "feat: isolate advisor test conversations"`

### Task 2: 只读策略与上下文快照

**Files:**

- Create: `app/services/advisor_lab.py`
- Modify: `app/services/chat_orchestration.py`, `app/services/chat_execution.py`, `app/services/chat_persistence.py`
- Test: `tests/test_advisor_lab_service.py`, `tests/test_chat_execution.py`

**Interfaces:**

- `AdvisorLabPolicy.blocked_operation(message: str) -> str | None`
- `build_advisor_lab_snapshot(*, prepared, intent, evidence, policy_events, run=None) -> dict[str, Any]`
- `ChatOrchestrationService.handle(..., conversation_mode="formal", advisor_lab=False)`
- `ChatAgentExecutionService.execute(..., read_only=False)`

- [ ] **Step 1: Write failing pure service tests**

```python
def test_snapshot_whitelists_context_and_redacts_internal_values():
    snapshot = build_advisor_lab_snapshot(prepared=fake_prepared(), intent="market_brief", evidence={"api_key": "secret", "market_date": "2026-08-03"}, policy_events=[], run={"id": "run-1", "status": "completed"})
    assert "api_key" not in repr(snapshot)
    assert snapshot["execution"]["run_id"] == "run-1"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_advisor_lab_service.py -q`

Expected: import failure for `app.services.advisor_lab`.

- [ ] **Step 3: Implement whitelist snapshot and no-write execution**

Capture route, selected history (40 messages / 500 characters), sanitized knowledge records, source summaries, time fields, exclusions, blocked reasons and execution status. Reject watchlist, memory, article/report/task, writeback, position/trade and approval requests before their existing branches. In `read_only=True`, skip structured writeback creation, deep-stock observation and evidence task capture.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_advisor_lab_service.py tests/test_chat_execution.py -q`

- [ ] **Step 5: Commit**

Run: `git add app/services/advisor_lab.py app/services/chat_orchestration.py app/services/chat_execution.py app/services/chat_persistence.py tests/test_advisor_lab_service.py tests/test_chat_execution.py && git commit -m "feat: add read-only advisor lab snapshots"`

### Task 3: 测试 API 和两栏静态页

**Files:**

- Modify: `app/main.py`, `app/static_assets.py`
- Create: `app/static/advisor-lab.html`, `app/static/advisor-lab.css`, `app/static/advisor-lab.js`
- Test: `tests/test_advisor_lab.py`

**Interfaces:**

- `GET /advisor-lab`
- `POST /me/advisor-lab/chat`
- `GET /me/advisor-lab/conversations`
- `GET /me/advisor-lab/conversations/{id}`
- `GET /me/advisor-lab/context/{assistant_message_id}`

- [ ] **Step 1: Write failing page and authorization test**

```python
def test_advisor_lab_context_is_user_scoped(client, app):
    create_user(client, "Lab Owner")
    response = client.post("/me/advisor-lab/chat", json={"message": "中兴通讯为什么下跌？", "execute_agent": False})
    assistant_id = response.json()["assistant_message_id"]
    assert client.get(f"/me/advisor-lab/context/{assistant_id}").json()["snapshot_version"] == "advisor_lab_context_v1"
    other = TestClient(app); create_user(other, "Lab Other")
    assert other.get(f"/me/advisor-lab/context/{assistant_id}").status_code == 404
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_advisor_lab.py::test_advisor_lab_context_is_user_scoped -q`

Expected: endpoint 404 before implementation.

- [ ] **Step 3: Implement the routes and page**

Use current session authentication and reuse `/me/chat/stream/{request_id}`. The page renders a left conversation and right `details` inspector with: question recognition, actual context, excluded context, evidence/gaps, execution, and safety. It uses `textContent` for server values and never renders writeback controls.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_advisor_lab.py tests/test_frontend_modules.py -q`

- [ ] **Step 5: Commit**

Run: `git add app/main.py app/static_assets.py app/static/advisor-lab.html app/static/advisor-lab.css app/static/advisor-lab.js tests/test_advisor_lab.py && git commit -m "feat: add standalone advisor lab"`

### Task 4: 写操作回归与单端口验证

**Files:**

- Modify: `README.md`
- Test: `tests/test_advisor_lab.py`, `tests/test_chat_context.py`, `tests/test_chat_execution.py`, `tests/test_frontend_modules.py`

- [ ] **Step 1: Write failing mutation-block test**

```python
def test_advisor_lab_blocks_mutation_without_changing_watchlist(client):
    create_user(client, "Read Only User")
    before = client.get("/me/watchlist").json()
    response = client.post("/me/advisor-lab/chat", json={"message": "把 000063 加入自选", "execute_agent": False})
    assert response.json()["intent"] == "advisor_lab_blocked"
    assert client.get("/me/watchlist").json() == before
```

- [ ] **Step 2: Verify RED then GREEN**

Run: `pytest tests/test_advisor_lab.py::test_advisor_lab_blocks_mutation_without_changing_watchlist -q`

- [ ] **Step 3: Document local access and run release checks**

Document the existing application command and `http://127.0.0.1:8000/advisor-lab`, explicitly stating that no front-end process is needed. Run: `python -m compileall -q app tests`; `pytest tests/test_advisor_lab.py tests/test_advisor_lab_service.py tests/test_chat_context.py tests/test_chat_execution.py tests/test_frontend_modules.py -q`; `docker compose --env-file staging.env.example config --quiet`.

## Self-review

- Task 1 covers durable session isolation and formal compatibility.
- Task 2 covers real context, redaction and API-enforced no-write behavior.
- Task 3 covers single-port UI, SSE reuse and authorization.
- Task 4 covers manual access, regression and deployment configuration checks.
