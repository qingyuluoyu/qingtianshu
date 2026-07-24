# 清数智算生产运行手册

更新日期：2026-07-24

## 1. 生产拓扑

生产 Compose 包含 PostgreSQL、Web/API、独立 Worker 和备份服务。Web 不执行金融
刷新任务；一个或多个 Worker 通过 PostgreSQL 原子领取任务。结构化业务数据、周期
计划、任务租约、重试和跨进程事件均在 PostgreSQL；用户工作区文件暂存在共享卷。

## 2. 每日检查

使用有效用户会话并携带 `X-Qingshu-Admin-Token` 请求：

```bash
curl -H "X-Qingshu-Admin-Token: $QINGSHU_ADMIN_API_TOKEN" \
  --cookie "$QINGSHU_SESSION_COOKIE" \
  http://127.0.0.1:8000/admin/operations/health
```

最低检查项：

- 业务 Schema 为 v1，运维 Schema 为 v3；
- 至少一个 Worker 为 `active`，最近心跳不超过 45 秒；
- `queue.expired_running = 0`；
- `queue.oldest_ready_age_seconds < 120`；
- `queue.failure_rate_24h < 0.05`，并逐条解释失败任务；
- 最近备份 `status = ok` 且不超过 26 小时。
- 成功/取消任务默认保留 7 天、失败任务保留 30 天；调整保留期前先评估审计需求和
  PostgreSQL 容量。
- 业务库后台成功审计和数据健康快照默认保留 30 天，失败审计保留 90 天。
- 核对业务库和运维库连接池的 `pool_available`、`requests_waiting`；持续等待说明
  应先排查慢查询和连接泄漏，再评估提高池上限。

服务器或容器内可直接运行同口径自检：

```bash
python scripts/check_operations.py \
  --require-postgres \
  --minimum-active-workers 1 \
  --max-queue-lag-seconds 600 \
  --max-failure-rate-24h 0.2
```

输出 `status=degraded` 时退出码为 1，便于 Docker、systemd 或云监控直接采集。
HTTP `/health` 用于 liveness，`/ready` 用于 readiness；负载均衡只应使用
`/ready`，不要用 `/health` 代替完整就绪检查。

建议生产告警阈值：

| 指标 | 警告 | 严重 |
|---|---:|---:|
| 活跃 Worker | 0 持续 1 分钟 | 0 持续 5 分钟 |
| 最老 ready 任务 | 120 秒 | 600 秒 |
| 24 小时失败率 | 5% | 20% |
| 过期运行租约 | ≥1 | ≥3 |
| 最近备份年龄 | 26 小时 | 48 小时 |
| 数据库连接等待 | 持续 30 秒 | 持续 5 分钟 |

## 3. 队列故障处理

1. 先查看 `/admin/operations/health` 和 `/admin/job-queue?status=failed`。
2. Worker 离线时先恢复 Worker，不要直接批量重试。
3. 确认上游数据源、数据库和磁盘正常后，对单个失败任务调用
   `POST /admin/job-queue/{job_id}/retry`。
4. 不确定任务是否幂等时禁止手工复制任务。系统是 at-least-once 语义，任务函数
   必须允许重复执行。
5. 租约过期任务会自动重新入队；达到最大次数后才进入失败归档。

## 4. 备份与恢复

手工备份：

```bash
python scripts/postgres_backup.py \
  --database-url "$QINGSHU_DATABASE_URL" \
  --output-dir "$QINGSHU_BACKUP_DIR"
```

成功 manifest 必须同时包含 `archive_verified=true` 和 SHA-256；只有文件存在但
归档无法被 `pg_restore --list` 解析时，不能算成功备份。

每周至少执行一次临时库恢复演练：

```bash
python scripts/postgres_restore_drill.py \
  "$QINGSHU_BACKUP_DIR/<backup>.dump" \
  --database-url "$QINGSHU_DATABASE_URL"
```

只有在明确的灾备窗口中才允许恢复正式目标库：

```bash
python scripts/postgres_restore.py \
  "$QINGSHU_BACKUP_DIR/<backup>.dump" \
  --database-url "$QINGSHU_DATABASE_URL" \
  --confirm-database qingshu \
  --clean
```

恢复后必须核验：

- 两个 Schema 版本；
- 用户、会话、自选股、研究对话和 Run 行数；
- 周期计划、等待/运行/失败任务数量；
- Worker 能注册、领取并完成一次 `data_quality_audit`；
- `/health`、`/admin/operations/health` 和前端真实登录路径。

## 5. 发布与回滚

1. 发布前完成全量 pytest、Ruff、编译和 Compose 配置解析。
2. 发布前创建数据库备份，并执行一次最近备份的临时库恢复演练。
3. 用 `staging.env.example` 创建 `.env.staging`，通过独立 Compose project 部署；
   确认迁移、Worker 心跳、队列延迟、备份和用户会话。
4. 生产发布期间只启动一个 Worker，健康稳定后再扩容。
5. 回滚应用代码不能回滚或删除已应用 Schema；不兼容 Schema 变更必须采用
   expand/contract 两阶段迁移。

Web 与 Worker 的 Schema 初始化已有 PostgreSQL advisory lock；仍建议先启动 Web
完成迁移，再逐步扩容 Worker，以缩小发布故障面。

Staging 默认映射到 `127.0.0.1:18000`，卷名带 `qingshu-staging` project 前缀。
停止时不要使用 `down -v`，否则会删除 staging 的恢复证据。

## 6. 当前生产边界

- 工作区文件尚未迁往对象存储，数据库备份不覆盖这些文件；
- 尚未接入 Prometheus 或云告警，当前以管理员健康接口作为采集源；
- 尚未建立独立 staging Compose 和自动化发布流水线；
- 外部行情、公告和模型 Provider 仍需分别配置凭据、限流与 SLA 监控。
