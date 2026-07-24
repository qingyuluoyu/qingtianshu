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

建议生产告警阈值：

| 指标 | 警告 | 严重 |
|---|---:|---:|
| 活跃 Worker | 0 持续 1 分钟 | 0 持续 5 分钟 |
| 最老 ready 任务 | 120 秒 | 600 秒 |
| 24 小时失败率 | 5% | 20% |
| 过期运行租约 | ≥1 | ≥3 |
| 最近备份年龄 | 26 小时 | 48 小时 |

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
3. 先部署 staging，确认迁移、Worker 心跳、队列延迟和用户会话。
4. 生产发布期间只启动一个 Worker，健康稳定后再扩容。
5. 回滚应用代码不能回滚或删除已应用 Schema；不兼容 Schema 变更必须采用
   expand/contract 两阶段迁移。

## 6. 当前生产边界

- 工作区文件尚未迁往对象存储，数据库备份不覆盖这些文件；
- 尚未接入 Prometheus 或云告警，当前以管理员健康接口作为采集源；
- 尚未建立独立 staging Compose 和自动化发布流水线；
- 外部行情、公告和模型 Provider 仍需分别配置凭据、限流与 SLA 监控。
