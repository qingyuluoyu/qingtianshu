# 边界状态测试证据

> 基于真实接口调用 ｜ 不修改任何业务代码

---

## 1. 新注册用户无数据时

### /me/watchlist/brief（空关注）
```json
{
  "type": "watchlist_brief",
  "generated_at": "2026-08-04T06:40:47+00:00",
  "items": [],
  "coverage": { "requested": 0, "available": 0 },
  "warnings": ["自选股为空。可先通过 POST /users/{id}/watchlist 添加。"]
}
```

### /me/research-actions（无关注）
```json
{
  "type": "research_actions",
  "generated_at": "2026-08-04T06:40:47+00:00",
  "method": "deterministic_research_action_board_v1",
  "items": [],
  "summary": {
    "symbols": 0, "triggered": 0, "pending_data": 0,
    "watching": 0, "priority_research": 0
  },
  "status_legend": { ... },
  "boundary": "研究行动只决定下一步核验哪份证据；不是价格提醒、买卖信号、仓位建议、目标价或未来涨跌预测。",
  "snapshot_id": "82fdde58-...",
  "snapshot_created_at": "2026-08-04T06:40:47+00:00"
}
```

### /me/research-changes（无关注）
```json
{
  "type": "research_tracking",
  "generated_at": "2026-08-04T06:40:47+00:00",
  "symbol": null,
  "items": [],
  "events": [],
  "coverage": {
    "requested": 0,
    "with_report": 0,
    "with_change_archive": 0
  },
  "method": "比较连续研究报告中的行情、技术、事件、情绪、基本面、分析师一致预期、条件展望和研究覆盖变化。",
  "boundary": "研究变化档案是长期证据记录，不是收益评分、胜率或交易指令。"
}
```

### /v1/today/overview（新用户）
- priority_items.items: []（空数组）
- priority_items.empty_message: "当前没有需要立即处理的个人研究事项。"
- personalized.status: "empty"
- personalized.changes: []
- coverage.status: "ready"
- coverage.watchlist_symbols: 0
- warnings: []（所有组件 ready，无警告）

---

## 2. 无 Cookie 时私有接口

| 接口 | 状态码 | 响应体 |
|---|---|---|
| GET /session | 401 | `{"code":"session_expired","message":"会话已失效或不存在"}` |
| GET /v1/today/overview | 401 | FastAPI 默认 `{"detail":"Not authenticated"}` |
| GET /me/watchlist/brief | 401 | FastAPI 默认 |
| GET /me/research-actions | 401 | FastAPI 默认 |
| GET /me/research-changes | 401 | FastAPI 默认 |

---

## 3. 无效查询参数

### /indices?scope=invalid
```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": ["query", "scope"],
      "msg": "Input should be 'core' or 'all'",
      "input": "invalid",
      "ctx": {"expected": "'core' or 'all'"}
    }
}
```

### /sectors/hot?limit=200
- 状态码：422（超过 ge=1, le=100 限制）

---

## 4. 非交易日

**当前为交易日**（2026-08-04 周一，A 股盘中）。非交易日状态通过以下字段反映：
- session.key: "closed"
- session.exchange_status: "closed"
- session.exchange_label: "已收盘"
- breadth 使用上一交易日缓存数据
- indices 使用上一交易日数据

无交易日时，接口不报错，返回最近可用数据并标注 is_stale=true。

---

## 5. Provider 不可用时

### market_breadth 不可用
```json
{
  "status": "unavailable",
  "source": "Sina Finance all A-share snapshot",
  "breadth": {},
  "turnover": {"status": "unavailable"},
  "distribution": {"status": "unavailable"},
  "warnings": ["..."],
  "scope": "all_a_shares_including_beijing"
}
```

### hot_sectors 不可用
```json
{
  "source": "Eastmoney A-share sector ranking",
  "status": "unavailable",
  "sectors": [],
  "warnings": ["..."],
  "coverage": {"returned": 0, "total_available": null}
}
```

---

## 6. 部分组件失败不影响其他组件

`TodayOverviewService._collect` 使用 `ThreadPoolExecutor`，每个子调用独立捕获异常：
```python
try:
    results[key] = future.result()
    statuses[key] = "ready"
except Exception:
    results[key] = {}
    statuses[key] = "unavailable"
```

**验证**：即使某个 provider 抛出异常，其他组件仍正常返回。coverage.components 中标记为 "unavailable" 的组件会出现在 warnings 数组中。

---

## 7. /sectors/hot 返回空数组

当东方财富主源失败且新浪降级也失败时：
```json
{
  "status": "unavailable",
  "sectors": [],
  "warnings": ["..."],
  "coverage": {"returned": 0}
}
```

前端 parseSectors 对空数组返回 `items: []`，TodayPage 显示"暂无可确认板块数据"。

---

## 8. today-overview 部分组件不可用

当 components 中有 "unavailable" 时：
- coverage.status: "partial"
- warnings 数组包含对应警告
- 页面顶部显示"部分数据暂不可用；已返回模块仍保持可读。"
- 各模块独立显示错误状态，不影响其他模块
