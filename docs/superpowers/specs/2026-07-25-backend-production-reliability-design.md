# 后端生产可靠性设计

## 目标

将 AI 研究任务从 HTTP 进程内后台执行迁移为可恢复、可取消、可限流和可审计的异步工作流；同时收紧会话与运维接口、补齐请求追踪，并使数据库结构以版本化迁移为唯一演进路径。

## 范围与非目标

本次只覆盖 AI 研究任务、会话安全、运维诊断、可观测性和 schema 演进。确定性金融计算、数据供应商口径、普通聊天 Agent 工作流和前端功能不改变。Redis 不保存研究结果、用户私有数据或 API 密钥；SQLite 继续作为研究状态、审计和业务数据的权威存储。

## 架构

Docker Compose 新增 Redis 与 `qingshu-worker`。API 服务在同一 SQLite 事务中创建研究 run、写入任务记录和 outbox 记录；投递 Redis 仅是加速路径。worker 消费 Redis Stream，并在启动和轮询时扫描未投递或超时中的 SQLite 任务，保证 Redis 故障或进程重启后任务仍可恢复。

任务记录具有 `pending`、`running`、`retry_wait`、`completed`、`failed`、`cancelled`、`expired` 状态。由于既有 `ai_research_runs.status` 的 CHECK 枚举不能安全扩展，新状态机使用新增的 `execution_status` 字段；公开 API 以该字段作为任务状态，旧 `status` 仅为旧调用方保留。每次状态变更使用 run 的整数版本号和期望旧状态进行 compare-and-set；不满足条件即返回冲突而不覆盖结果。创建研究任务要求客户端提供 `Idempotency-Key`，键在用户范围内绑定请求摘要；同键同请求返回原 run，不同请求返回冲突。

每个用户同一时间最多一个运行中的 AI 研究任务。默认单 run 最大三次尝试；模型成本达到 per-run 或 per-user rolling-window 预算时，在调用前拒绝或取消任务。worker 在每一步和模型调用前检查取消标记、尝试次数、运行时限及预算。模型和供应商调用写入审计记录，但日志只保留类型、耗时、状态、模型、用量与脱敏错误摘要，不写入密钥、Cookie、完整提示词或用户持仓。

## 接口契约

`POST /me/ai-research/runs` 增加必填 `Idempotency-Key` 请求头，成功仍返回 202 和既有公开 run 字段，额外返回 `idempotent_replay`。新增 `POST /me/ai-research/runs/{run_id}/cancel`：仅任务处于 `pending`、`running` 或 `retry_wait` 时可取消，返回更新后的 run。既有 retry、dimension 与 detail 接口保留，但只入队，不再使用 FastAPI `BackgroundTasks`。

`/sessions/claim` 删除。首次匿名会话仍由产品入口创建，但生产环境必须使用 HTTPS，并强制 `Secure`、`HttpOnly`、`SameSite=Strict` Cookie；登录后与敏感账户动作轮换 session token。创建用户、创建研究任务、重试和取消接口使用用户维度限流，超限返回 429 和 `Retry-After`。

`/system/background` 与 `/system/data-health` 改为仅接受运维 Bearer token 的接口。`/health` 保持匿名，但只返回安全的聚合状态。

## 数据模型与迁移

新增 expand-only migration：

- `ai_research_runs`：`version`、`idempotency_key`、`request_fingerprint`、`cancel_requested_at`、`attempt_count`、`max_attempts`、`next_attempt_at`、`started_at`、`budget_limit_usd`、`cost_usd`、`expires_at`。
- `research_tasks`：任务类型、run、用户、状态、尝试、可见时间、Redis 消费标识、租约和最后错误。
- `research_task_outbox`：事务性待投递记录与投递时间。
- `provider_call_audits`：request/trace ID、run、供应商、模型、操作、耗时、用量、成本、状态与脱敏错误。
- `rate_limit_windows`：用户、动作、窗口起点和使用量。
- `user_sessions`：轮换关系和最近轮换时间。

初始业务表 DDL 从 `Database.initialize()` 移入完整的 `0001` 基线 migration。既有数据库仍以 `schema_migrations` 为准，后续 migration 仅 expand，不删除已使用字段。发布前先备份 SQLite，先部署兼容 API/worker 与 migration，再启用新入口；回滚代码时保留新增字段与表，采用前向修复而非 schema 回滚。

## 可观测性与错误处理

HTTP 中间件生成或接收 `X-Request-ID`，并在响应中回传。任务创建将该值保存为 trace ID；worker 从任务恢复该 trace ID。结构化日志包含 request/trace ID、用户哈希、任务/run ID、状态迁移、供应商调用、耗时和成本。所有外部调用使用明确 timeout；仅网络超时、429 和 5xx 可有限重试，参数、权限、预算和证据校验错误不重试。

## 测试与验收

测试覆盖同键重放、不同载荷冲突、并发 CAS、取消、超时恢复、最大重试、用户并发限制、预算拒绝、Redis 暂不可用后的 outbox 补发、worker 接管、运维权限、session rotation、Secure 配置与限流。迁移测试同时验证全新数据库和既有 schema 升级。部署验证包括 Compose 启动、worker 消费、API 健康检查和 Redis 重启后的任务恢复。

## 成本与兼容性

Redis 增加一个常驻轻量服务和一个 worker 容器；它避免 HTTP 进程重启丢任务，并通过并发与预算上限降低模型成本失控风险。既有研究读取接口与公开返回结构保持兼容；创建研究任务的客户端需补充 `Idempotency-Key`，前端在同次提交期间复用同一 key。
