# 清数智算第 0E 轮：正式账号认证与用户数据隔离审计报告

**基线**: d0a9b9b75200d4b89452c803a14bcc1add136481 (frontend-backend-baseline-0c-20260804)
**审计日期**: 2026-08-04
**审计范围**: 只读代码审查 + 本地开发数据库查询
**约束**: 未修改任何源码、未修改数据库 schema、未创建 frontend/、未创建测试账号

---

## 执行摘要

### 最终结论

**B. 后端只有匿名会话，需要先由 Codex 实现正式认证后端。**

当前系统没有任何账号密码认证能力。所有用户均为匿名创建，仅通过随机 session token 识别。数据库 users 表不存在 account、phone、password、password_hash 等字段。无任何密码哈希库依赖。无任何注册/登录/修改密码/找回密码接口。

---

## 任务 1：当前用户与会话数据模型

### users 表

| 字段 | 类型 | NULL | 默认值 | 约束 |
|------|------|------|--------|------|
| id | TEXT | NO | (无) | PRIMARY KEY |
| name | TEXT | NO | (无) | NOT NULL |
| workspace_path | TEXT | NO | (无) | UNIQUE |
| created_at | TEXT | NO | (无) | NOT NULL |

**索引**:
- `users_pkey`: UNIQUE INDEX on id
- `users_workspace_path_key`: UNIQUE INDEX on workspace_path

**外键**: 无（被引用方）

**源码位置**:
- DDL: `app/domain_schema.py:6-11`
- create_user: `app/db.py:452-466`
- get_user: `app/db.py:481-487`

### user_sessions 表

| 字段 | 类型 | NULL | 默认值 | 约束 |
|------|------|------|--------|------|
| id | TEXT | NO | (无) | PRIMARY KEY |
| token_hash | TEXT | NO | (无) | UNIQUE |
| user_id | TEXT | NO | (无) | FK → users(id) ON DELETE CASCADE |
| created_at | TEXT | NO | (无) | NOT NULL |
| expires_at | TEXT | NO | (无) | NOT NULL |
| last_seen_at | TEXT | NO | (无) | NOT NULL |
| revoked_at | TEXT | YES | NULL | (无) |

**索引**:
- `user_sessions_pkey`: UNIQUE INDEX on id
- `user_sessions_token_hash_key`: UNIQUE INDEX on token_hash
- `idx_user_sessions_user_expiry`: INDEX on (user_id, expires_at DESC)

**外键**:
- `user_sessions_user_id_fkey`: user_id → users.id ON DELETE CASCADE

**Session token 保存方式**:
- 原始 token 不保存
- 保存 SHA256(token) 的 hex 摘要
- 源码: `app/db.py:489-521` (`_session_token_hash` 使用 `hashlib.sha256`)

**代码位置**:
- set_session_cookie: `app/main.py:805-814`
- require_session_user: `app/main.py:816-820`
- create_user_session: `app/db.py:493-521`
- get_user_by_session: `app/db.py:523-545`
- revoke_user_session: `app/db.py:547-557`

---

## 任务 2：密码是否真的被保存和验证

### 明确结论

**当前不存在任何密码认证能力。**

1. **UserCreate 模型不接受 password**:
   ```python
   # app/api_models.py:8-9
   class UserCreate(BaseModel):
       name: str = Field(min_length=1, max_length=80)
   ```
   Pydantic 会忽略未声明的 password 字段（extra=ignore 默认行为）。

2. **POST /users 不读取 password**:
   ```python
   # app/main.py:1058-1064
   def create_user(payload: UserCreate, response: Response):
       user = database.create_user(payload.name)  # 只使用 name
   ```
   ```python
   # app/db.py:452-466
   def create_user(self, name: str):
       connection.execute(
           "INSERT INTO users(id, name, workspace_path, created_at) VALUES (?, ?, ?, ?)",
           (user_id, name.strip(), str(workspace), created_at),
       )
   ```

3. **数据库 users 表不存在密码相关列**:
   - 无 account
   - 无 username
   - 无 phone
   - 无 password
   - 无 password_hash
   - 无 password_digest

4. **无密码哈希依赖**:
   - argon2: NOT installed
   - bcrypt: NOT installed
   - passlib: NOT installed
   - pwdlib: NOT installed

5. **无密码验证函数**: 全代码库搜索无任何密码比对逻辑

6. **无真正的登录接口**: 全代码库搜索无 /auth/login、/auth/register、/signup 等路由

7. **成功创建 Cookie 的含义**: 仅代表创建匿名个人空间并建立匿名会话

### 证据链总结

```
请求: POST /users {"name": "网页体验用户"}
  ↓ Pydantic 忽略 password 字段
  ↓ database.create_user("网页体验用户")
  ↓ INSERT INTO users(id, name, workspace_path, created_at) VALUES (...)
  ↓ database.create_user_session(user_id, ttl_days)
  ↓ INSERT INTO user_sessions(id, token_hash, user_id, ...) VALUES (...)
  ↓ set_session_cookie(response, session)  # 设置 qingshu_session cookie
```

密码字段全程未被读取、未被保存、未被验证。

---

## 任务 3：所有认证相关路由

### 现有认证/会话路由

| 方法 | 路径 | 请求模型 | 响应 | 是否验证密码 | 是否写 Cookie | 当前用途 |
|------|------|----------|------|-------------|--------------|----------|
| POST | /users | UserCreate(name) | 用户信息 + Cookie | 否 | 是 | 创建匿名个人空间 |
| GET | /session | (无) | 用户信息 | 否 | 否 | 获取当前会话 |
| DELETE | /session | (无) | 204 No Content | 否 | 否(清除) | 退出/吊销会话 |
| POST | /sessions/claim | LegacySessionClaim(user_id) | 用户信息 + Cookie | 否 | 是 | 迁移旧匿名空间 |

### 不存在的路由

- **POST /auth/register** — 不存在
- **POST /auth/login** — 不存在
- **PUT /me/password** — 不存在
- **POST /auth/forgot-password** — 不存在
- **POST /auth/reset-password** — 不存在
- **GET /me/risk-profile** — 存在（但返回风险画像问卷，非认证）
- **POST /me/uploads/images** — 存在（但仅需有效会话，非认证）

### 辅助认证函数

| 函数 | 位置 | 行为 |
|------|------|------|
| require_session_user | main.py:816-820 | 从 Cookie 读取 token_hash → JOIN users 验证 → 返回 user |
| require_user | main.py:842-846 | require_session_user + 校验 user_id 匹配 |
| require_admin_api | main.py:831-840 | require_session_user + x-qingshu-admin-token 校验 |
| set_session_cookie | main.py:805-814 | 设置 HttpOnly + SameSite=strict + Secure(生产) |

---

## 任务 4：个人数据隔离矩阵

### 数据表隔离检查

| 数据对象 | 数据表 | 是否有 user_id | 外键/索引 | 查询是否过滤 user_id | 对象详情是否二次校验归属 | 风险评级 |
|----------|--------|--------------|-----------|---------------------|------------------------|---------|
| 用户 | users | 是(PK) | PK on id | 是 | 是 | 已确认安全 |
| 会话 | user_sessions | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 自选股 | watchlist | 是 | PK(user_id, symbol) | 是 | 是 | 已确认安全 |
| 对话 | conversations | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 对话消息 | conversation_messages | 是 | FK→conversations(id) CASCADE + 冗余 user_id | 是 | 是 | 已确认安全 |
| 研究运行 | runs | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 个股工作区 | stock_workspaces | 是 | UNIQUE(user_id, symbol) | 是 | 是 | 已确认安全 |
| 个股关系历史 | stock_relation_history | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 论点版本 | thesis_versions | 是 | FK→stock_workspaces CASCADE + 冗余 user_id | 是 | 是 | 已确认安全 |
| AI 回写候选 | ai_writeback_candidates | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 观察任务 | observation_tasks | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 观察任务历史 | observation_task_history | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 记忆 | memories | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 风险画像 | risk_profile_versions | 是 | UNIQUE(user_id, version_no) | 是 | 是 | 已确认安全 |
| 持仓开仓 | position_openings | 是 | UNIQUE(user_id, idempotency_key) | 是 | 是 | 已确认安全 |
| 持仓操作 | position_operations | 是 | UNIQUE(user_id, idempotency_key) | 是 | 是 | 已确认安全 |
| 操作修订 | operation_revisions | 是 | UNIQUE(user_id, idempotency_key) | 是 | 是 | 已确认安全 |
| 持仓调整 | position_adjustments | 是 | UNIQUE(user_id, idempotency_key) | 是 | 是 | 已确认安全 |
| 操作上下文 | operation_context_snapshots | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 交易复盘 | trade_reviews | 是 | UNIQUE(user_id, workspace_id, ...) | 是 | 是 | 已确认安全 |
| 复盘版本 | trade_review_versions | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 操作计划 | action_plans | 是 | UNIQUE(id, user_id, workspace_id) | 是 | 是 | 已确认安全 |
| 操作计划历史 | action_plan_history | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 深度个股会话 | deep_stock_sessions | 是 | UNIQUE(user_id, symbol) | 是 | 是 | 已确认安全 |
| 用户变化链接 | user_change_links | 是 | UNIQUE(user_id, change_event_id) | 是 | 是 | 已确认安全 |
| 研究优先级快照 | research_priority_snapshots | 是 | UNIQUE(user_id, fingerprint) | 是 | 是 | 已确认安全 |
| 研究行动快照 | research_action_snapshots | 是 | UNIQUE(user_id, fingerprint) | 是 | 是 | 已确认安全 |
| 对话质量快照 | conversation_quality_snapshots | 是 | UNIQUE(user_id, fingerprint) | 是 | 是 | 已确认安全 |
| 补证任务 | evidence_tasks | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 用户上传 | user_uploads | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 知识资料 | knowledge_documents | 是(owner_user_id) | FK→users(id) CASCADE (可为 NULL) | 是 | 是 | 已确认安全 |
| 文章 | articles | 是 | FK→users(id) CASCADE | 是 | 是 | 已确认安全 |
| 研究报告 | research_reports | 否 | 无 user_id | 不适用 | 不适用 | 全局数据(系统生成) |
| 变化事件 | change_events | 否 | 无 user_id | 不适用 | 不适用 | 全局数据(系统生成) |
| 市场缓存 | market_cache | 否 | 无 user_id | 不适用 | 不适用 | 全局数据 |
| 财经数据 | financial_periods 等 | 否 | 无 user_id | 不适用 | 不适用 | 全局数据 |

### 关键隔离机制验证

#### 1. API 层隔离
所有个人数据 API 统一使用 `require_session_user(request)` 或 `require_user(request, user_id)` 获取当前用户。`require_user` 额外校验路径参数 user_id 与会话 user_id 一致。

#### 2. 二次归属校验
- `get_conversation(user_id, conversation_id)` — WHERE id=? AND user_id=?
- `get_conversation_message(user_id, message_id)` — WHERE id=? AND user_id=?
- `_plan_by_id(connection, user_id, plan_id)` — WHERE id=? AND user_id=?
- `_review_by_id(connection, user_id, review_id)` — WHERE id=? AND user_id=?
- `_task_for_user(connection, user_id, task_id)` — WHERE id=? AND user_id=?
- `get_deep_stock_session(user_id, symbol)` — WHERE user_id=? AND symbol=?

#### 3. advisor_test / formal 隔离
- 列表接口: `list_conversations(user_id, conversation_mode="advisor_test")` 按 mode 过滤
- 详情接口: `get_my_conversation` 校验 `conversation_mode == "formal"`，拒绝 advisor_test
- advisor lab 上下文: 显式校验 `conversation_mode == "advisor_test"`
- **隔离状态**: 已确认安全

#### 4. SSE request_id 校验
```python
# app/services/agent_stream.py:35-44, 77-82
def open(self, request_id, user_id):
    state = self._requests.get(request_id)
    if state.user_id != user_id:
        raise PermissionError("Agent stream does not belong to this user")

def stream(self, request_id, user_id):
    state = self._requests.get(request_id)
    if state is None or state.user_id != user_id:
        raise PermissionError("Agent stream does not belong to this user")
```
**隔离状态**: 已确认安全

#### 5. 上传文件归属校验
```python
# app/db.py:601-608
def get_user_upload(self, user_id, upload_id):
    return connection.execute(
        "SELECT * FROM user_uploads WHERE user_id = ? AND id = ?",
        (user_id, upload_id),
    ).fetchone()
```
**隔离状态**: 已确认安全

#### 6. 持仓/交易操作隔离
所有 position_ledger 和 trade_workflow 方法均以 user_id 为首要参数，内部所有查询均带 user_id 过滤。
**隔离状态**: 已确认安全

### 隔离总体评级

**已确认安全** — 当前匿名会话模型下，所有个人数据表均有 user_id 外键，所有 API 路由均通过 `require_session_user` 提取用户身份，所有 Service/Database 查询均显式过滤 user_id。未发现跨用户读写路径。

---

## 任务 5：数据库现有用户数据规模

### 用户统计

| 数据表/对象 | 记录数 | 涉及用户数 | 是否可能只是测试数据 |
|------------|--------|-----------|-------------------|
| users | 17 | 17 | 部分为测试用户 |
| 有效 sessions | 15 | 15 | 测试 + 合同采集 |
| watchlist 条目 | 24 | 6 | 是 |
| conversations | 22 | 6 | 是 |
| conversation_messages | 84 | 6 | 是 |
| runs | 189 | 6 | 是 |
| position_openings | 0 | 0 | - |
| position_operations | 0 | 0 | - |
| user_uploads | 0 | 0 | - |
| memories | 0 | 0 | - |
| knowledge_documents(用户) | 6 | 6 | 是 |
| risk_profile_versions | 0 | 0 | - |
| deep_stock_sessions | 6 | 2 | 是 |
| trade_reviews | 0 | 0 | - |
| action_plans | 0 | 0 | - |
| observation_tasks | 0 | 0 | - |
| ai_writeback_candidates | 0 | 0 | - |
| articles | 3 | 1 | 是 |

### 用户构成分析

| 用户名称 | 类型推断 |
|---------|---------|
| 系统市场编辑 | 系统内置 |
| 网页体验用户 x4 | 匿名测试用户 |
| dazhu | 开发者个人测试 |
| Advisor Lab Smoke/Verify | 测试用户 |
| contract_test_user x2 | 合同采集测试 |
| frontend_contract_test_001/003 | 合同采集测试 |
| frontend_today_test | 合同采集测试 |
| frontend_watchlist_test | 合同采集测试 |
| frontend_stock_test | 合同采集测试 |
| frontend_error_test | 合同采集测试 |
| frontend_sse_test | 合同采集测试 |

**结论**: 17 个用户全部为开发和测试数据，无真实生产用户。数据量小（24 条关注、22 个对话、189 次运行），可安全清除重建。

---

## 任务 6：匿名会话迁移风险分析

### 当前匿名用户数据规模

- 17 个用户，全部为测试/开发数据
- 最大数据量：189 次 AI 运行、84 条消息、24 条关注
- 无持仓、无交易复盘、无上传文件、无记忆

### 三种方案评估

#### 方案 A：删除现有测试数据，正式账号重新注册

- 优点：数据干净，无迁移复杂度
- 缺点：所有测试数据丢失
- 适用性：**当前阶段最佳** — 17 个用户全为测试数据，无真实用户

#### 方案 B：用户登录后绑定当前匿名空间

- 优点：保留测试数据
- 缺点：需要实现匿名空间绑定逻辑，增加复杂度
- 适用性：不必要 — 无真实用户数据需保留

#### 方案 C：保留匿名模式和正式账号双轨运行

- 优点：向后兼容
- 缺点：维护两套用户体系，代码复杂度翻倍
- 适用性：不推荐 — 增加长期维护成本

### 推荐方案

**方案 A** — 删除现有测试数据，正式账号重新注册。

理由：
1. 17 个用户全为测试数据，无真实用户需保留
2. 代码中已有 `POST /sessions/claim` 迁移路径（仅限 "网页体验用户"）
3. 正式账号上线后，不再自动创建匿名用户
4. 最小化后续维护复杂度

### 迁移边界

- 不需要迁移接口（直接注册新账号）
- 不会出现两个 user_id 的问题
- 原有数据直接清除
- 不存在重复账号或数据丢失风险（测试数据无价值）

---

## 任务 7：正式认证接口合同建议

### POST /auth/register

```
请求:
{
  "account": "string",      // 6-20 位字母数字下划线，唯一
  "phone": "string",        // 中国大陆手机号，11 位数字，唯一
  "password": "string"      // 8-64 位
}

成功: 201 Created
响应:
{
  "id": "uuid",
  "account": "string",
  "masked_phone": "138****1234",
  "created_at": "ISO8601"
}
Set-Cookie: qingshu_session=...; HttpOnly; Secure(生产); SameSite=strict; Max-Age=31536000

错误:
- 409: {"detail": "账号已存在"}  (account 重复)
- 409: {"detail": "手机号已注册"} (phone 重复)
- 422: {"detail": "密码长度需为 8-64 位"} (弱密码)
- 422: {"detail": "手机号格式不正确"} (格式错误)
```

**注意**: account 和 phone 需标准化（trim、全角转半角、去空格）后查重。

### POST /auth/login

```
请求:
{
  "login": "string",        // 账号或手机号
  "password": "string"      // 密码
}

成功: 200 OK
响应: 同 register

错误:
- 401: {"detail": "账号或密码错误"}  (不区分账号不存在/密码错误)
- 422: {"detail": "请输入账号和密码"} (参数缺失)

安全行为:
- 登录成功后轮换 session（吊销旧 session，创建新 session）
- 设置新的 Set-Cookie
```

### DELETE /session

保持当前行为（204 No Content + 清除 Cookie）。

### GET /session

建议限制返回字段：
```json
{
  "id": "uuid",
  "account": "string",
  "masked_phone": "138****1234",
  "created_at": "ISO8601",
  "session_expires_at": "ISO8601"
}
```

**不得返回**: password_hash、完整 session token、内部权限密钥。

### 旧 API 兼容策略

| 旧 API | 建议 | 原因 |
|--------|------|------|
| POST /users | **保留但标记废弃** | 现有测试/合同采集依赖 |
| POST /sessions/claim | **保留但标记废弃** | 旧匿名空间迁移 |
| GET /session | **修改响应格式** | 返回新字段结构 |
| DELETE /session | **保持** | 行为不变 |

### 新增 API 列表

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | /auth/register | 注册正式账号 |
| POST | /auth/login | 登录 |
| POST | /auth/logout | 可选，与 DELETE /session 等价 |
| GET | /auth/session | 可选，与 GET /session 等价 |
| PUT | /me/password | 修改密码 |
| POST | /auth/forgot-password | 找回密码(第一期可暂缓) |
| POST | /auth/reset-password | 重置密码(第一期可暂缓) |

---

## 任务 8：安全基线核查

### 当前状态 vs 正式账号要求

| 安全项 | 当前状态 | 正式账号要求 | 差距 |
|--------|---------|------------|------|
| 密码哈希 | 无 | argon2 或 bcrypt | **P0** — 需新增 |
| 单独加盐 | 无 | 每用户随机 salt | **P0** — 需新增 |
| Session 轮换 | 无 | 登录后吊销旧 session | **P1** — 需新增 |
| 登录频率限制 | 无 | 5次/分钟 | **P1** — 需新增 |
| 账号标准化 | 无 | trim、全角转半角 | **P1** — 需新增 |
| 手机号标准化 | 无 | 去前导空格、去+86 | **P1** — 需新增 |
| Cookie Secure | False(开发) | True(生产) | 已有配置开关，生产需设为 True |
| SameSite | strict | strict | 已正确 |
| Session 有效期 | 365 天 | 建议 7-30 天 | **P1** — 过长 |
| 退出全部设备 | 无 | 支持 | **P2** — 需新增 |
| 登录错误信息 | N/A | 不泄露账号存在性 | **P1** — 需注意 |
| 密码日志 | N/A | 禁止记录 | 需确保中间件不记录 |
| OpenAPI 示例 | N/A | 不含敏感字段 | 需检查 |
| 暴力破解防护 | 无 | 频率限制 | **P1** — 需新增 |

### 数据库 schema 变更需求

```sql
-- 新增列
ALTER TABLE users ADD COLUMN account TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN salt TEXT NOT NULL DEFAULT '';

-- 新增约束
CREATE UNIQUE INDEX uq_users_account ON users(account) WHERE account != '';
CREATE UNIQUE INDEX uq_users_phone ON users(phone) WHERE phone != '';
```

---

## 任务 9：下一轮实施边界

### 问题回答

1. **当前到底有没有真实账号密码登录？**
   - **没有**。仅有匿名会话，通过随机 token + HttpOnly Cookie 识别。

2. **账号、手机号和密码目前是否存在于数据库？**
   - **不存在**。users 表只有 id, name, workspace_path, created_at。

3. **当前密码字段是否被忽略？**
   - **不适用** — 密码字段从未存在于数据模型中。UserCreate 仅声明 name 字段，Pydantic 会静默忽略未声明的 password。

4. **当前个人数据隔离是否可信？**
   - **可信**。所有个人数据表均有 user_id 外键，所有 API 均通过 `require_session_user` 获取用户身份，所有查询均显式过滤 user_id。未发现跨用户访问路径。

5. **是否发现跨用户读取或写入风险？**
   - **未发现**。Service 层和 Database 层均严格按 user_id 过滤。

6. **现有匿名用户数据是否需要迁移？**
   - **不需要**。17 个用户全为测试数据，可直接清除重建。

7. **正式账号系统应新增或修改哪些表？**
   - 修改 users 表：新增 account, phone, password_hash, salt 列
   - 新增 user_login_attempts 表（登录频率限制）

8. **应新增哪些 API？**
   - POST /auth/register
   - POST /auth/login
   - PUT /me/password
   - (可选) POST /auth/forgot-password
   - (可选) POST /auth/reset-password

9. **应保留哪些旧 API？**
   - GET /session — 修改返回格式
   - DELETE /session — 保持
   - POST /users — 保留但标记废弃（向后兼容）
   - POST /sessions/claim — 保留但标记废弃

10. **是否可以让 Codex 开始做登录后端？**
    - **可以**。当前系统已具备完整的匿名会话基础设施（token 生成、hash 存储、Cookie 设置、会话验证），只需在现有基础上增加账号密码注册/登录逻辑。

11. **登录后端完成前，是否允许创建 React 正式页面？**
    - **可以**。React 页面可以先搭建 UI 框架和页面结构，登录弹窗可以先做 UI mock。但正式页面不应硬编码任何用户数据。

12. **下一轮 Codex 最多做哪 3 项任务？**
    - **任务 1**: 实现 POST /auth/register（账号密码注册 + 密码哈希 + Cookie）
    - **任务 2**: 实现 POST /auth/login（密码验证 + Session 轮换 + Cookie）
    - **任务 3**: 修改 GET /session 返回新字段结构（account, masked_phone）

---

## 附录：关键代码位置索引

| 功能 | 文件 | 行号 |
|------|------|------|
| UserCreate 模型 | app/api_models.py | 8-9 |
| create_user 路由 | app/main.py | 1058-1064 |
| create_user DB 方法 | app/db.py | 452-466 |
| Session cookie 设置 | app/main.py | 805-814 |
| require_session_user | app/main.py | 816-820 |
| Session 创建 | app/db.py | 493-521 |
| Session 验证 | app/db.py | 523-545 |
| Session 吊销 | app/db.py | 547-557 |
| users 表 DDL | app/domain_schema.py | 6-11 |
| user_sessions 表 DDL | app/domain_schema.py | 13-21 |
| 密码 hash 函数 | app/db.py | 489-491 |
| Session TTL 配置 | app/config.py | 100 |
| Cookie Secure 配置 | app/config.py | 101 |
| 所有个人数据 API | app/main.py | 分散 |
| 数据库隔离查询 | app/db.py | 分散 |
| Service 层隔离 | app/services/*.py | 分散 |

---

## 附录：禁止项执行确认

- [x] 未修改任何源码
- [x] 未修改数据库 schema
- [x] 未写 migration
- [x] 未创建 frontend/
- [x] 未实现登录弹窗
- [x] 未创建正式账号
- [x] 未输出真实用户数据（仅显示名称模式和 ID 前缀）
- [x] 未输出密码哈希（不存在）
- [x] 未输出 Cookie 或 session token
- [x] 未使用生产数据库
- [x] 未把前端隐藏当作数据隔离
- [x] 未把 POST /users 成功当作密码认证成功
