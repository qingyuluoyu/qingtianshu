# 今日观察页面开发前数据采集报告

> 审计日期：2026-08-04 ｜ 基于真实接口调用 + 代码检索 ｜ 不修改任何文件
> 测试数据库：qingshu_auth_test ｜ 测试用户：audit596489（正式注册账号）

---

## 任务 1：9 个接口真实响应

### 1.1 GET /session

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.02s |
| 是否依赖用户 | 是（需要 Cookie） |

**完整响应结构**：
```json
{
  "id": "uuid",
  "account": "string | null",
  "name": "string",
  "masked_phone": "+86********XX | null",
  "auth_type": "account" | "legacy_anonymous",
  "is_registered": boolean,
  "created_at": "ISO8601",
  "session_expires_at": "ISO8601 | null"
}
```

**顶层字段**：id, account, name, masked_phone, auth_type, is_registered, created_at, session_expires_at
**null 字段**：account（匿名用户为 null）, masked_phone（无手机号为 null）, session_expires_at（某些情况）
**时间格式**：ISO 8601 带时区（`2026-08-04T06:40:42+00:00`）
**不存在的字段**：password, password_hash, token, phone（返回 masked_phone）

### 1.2 GET /v1/today/overview

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 3.39s |
| 是否依赖用户 | 是（`require_session_user`） |

**完整响应结构**：
```json
{
  "contract_version": "today_overview_v1",
  "method_version": "deterministic_today_overview_v1",
  "generated_at": "ISO8601",
  "session": {
    "key": "intraday" | "closed" | ...,
    "label": "盘中" | "已收盘" | ...,
    "exchange_status": "open" | "closed",
    "exchange_label": "交易中" | "已收盘",
    "market_local_time": "ISO8601+08:00",
    "calendar_status": "verified" | "fallback",
    "method": "exchange_calendar_v1"
  },
  "summary": {
    "headline": "string",
    "session_label": "string",
    "priority_count": number,
    "related_change_count": number,
    "market_date": "YYYY-MM-DD"
  },
  "priority_items": {
    "items": [...],
    "total_visible": number,
    "ranking_method": "string",
    "empty_message": "string | null"
  },
  "market": {
    "indices": [...],
    "breadth": {...},
    "industries": {...},
    "styles": {
      "status": "not_available",
      "message": "string"
    },
    "risk_agenda": {
      "status": "available" | "empty" | "not_available",
      "pending_unread": number,
      "items": [...],
      "message": "string"
    }
  },
  "personalized": {
    "status": "empty" | "partial" | "ready",
    "watchlist_count": number,
    "changes": [],
    "stock_overview": [],
    "coverage": {
      "event_whitelist_complete": boolean,
      "requested": number,
      "with_report": number,
      "with_change_archive": number,
      "enabled_event_types": [...],
      "uncovered_event_types": [...],
      "source_policy": "string",
      "event_scope": "string"
    },
    "empty_message": "string",
    "boundary": "string"
  },
  "coverage": {
    "components": {
      "tasks": "ready" | "unavailable",
      "writebacks": "ready" | "unavailable",
      "changes": "ready" | "unavailable",
      "actions": "ready" | "unavailable",
      "trade_reviews": "ready" | "unavailable",
      "breadth": "ready" | "unavailable",
      "whitelist_changes": "ready" | "unavailable",
      "indices": "ready" | "unavailable",
      "industries": "ready" | "unavailable"
    },
    "watchlist_symbols": number,
    "status": "ready" | "partial"
  },
  "warnings": [],
  "boundary": "string"
}
```

**priority_items.item 字段**（每个 item）：
- `id`: string（如 `"change-event:xxx"` / `"trade-review:xxx"` / `"observation-task:xxx"`）
- `kind`: "change_event" | "trade_review" | "observation_task" | "draft_confirmation" | "research_action"
- `category`: "change_event" | "trade_review" | "risk_review" | "user_task" | "draft_confirmation" | "evidence_gap" | "research_task"
- `title`: string
- `detail`: string | null
- `symbol`: string | null
- `name`: string | null
- `status`: string（如 "pending", "in_progress", "triggered", "draft"）
- `status_label`: string | null
- `priority`: "high" | "normal" | "low"
- `due_at`: string | null
- `overdue`: boolean
- `rank_reason`: string
- `source_type`: string
- `source_ref_id`: string | null
- `updated_at`: string | null
- `action`: { type: string, ... }

**所有枚举值**：
- session.key: "intraday", "closed"
- kind: "change_event", "trade_review", "observation_task", "draft_confirmation", "research_action"
- category: "change_event", "trade_review", "risk_review", "user_task", "draft_confirmation", "evidence_gap", "research_task"
- action.type: "open_change_event", "open_trade_review", "open_stock_tasks", "open_stock_research"
- coverage.status: "ready", "partial"

### 1.3 GET /indices?scope=all&group=china

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.82s |
| 是否依赖用户 | 否（公开接口） |

**完整响应结构**：
```json
{
  "generated_at": "ISO8601",
  "scope": "all" | "core",
  "group": "china" | null,
  "coverage": {
    "requested": number,
    "available": number
  },
  "warnings": ["string"],
  "indices": [
    {
      "symbol": "000001.SS",
      "name": "上证综指",
      "region": "中国",
      "group": "china",
      "status": "available" | "unavailable",
      "metrics": {
        "latest_close": number | null,
        "return_1d_pct": number | null,
        "return_5d_pct": number | null,
        "return_20d_pct": number | null,
        "return_60d_pct": number | null,
        "ma20": number | null,
        "ma60": number | null,
        "volatility_20d_annualized_pct": number | null,
        "max_drawdown_60d_pct": number | null,
        "return_1d_base_date": "string | null",
        "return_1d_end_date": "string | null",
        "return_5d_base_date": "string | null",
        "return_5d_end_date": "string | null",
        "return_20d_base_date": "string | null",
        "return_20d_end_date": "string | null",
        "return_60d_base_date": "string | null",
        "return_60d_end_date": "string | null",
        "rsi_14": number | null,
        "macd_12_26": number | null,
        "macd_signal_9": number | null,
        "macd_histogram": number | null,
        "bollinger_upper_20": number | null,
        "bollinger_middle_20": number | null,
        "bollinger_lower_20": number | null,
        "bollinger_position_20": number | null,
        "atr_14_pct": number | null,
        "volume_ratio_5_20": number | null,
        "technical_state": "string | null",
        "technical_method": "string",
        "trend_state": "string | null",
        "return_1d_status": "string"
      },
      "latest_bar": {
        "timestamp": "ISO8601",
        "open": number,
        "close": number,
        "adjusted_close": number,
        "high": number,
        "low": number,
        "volume": number
      },
      "recent_bars": [...],
      "source": "string",
      "market_timestamp": "ISO8601 | null",
      "fetched_at": "ISO8601",
      "is_stale": boolean,
      "coverage": {
        "requested_range": "string",
        "interval": "string",
        "points": number,
        "first_timestamp": "string",
        "last_timestamp": "string",
        "dropped_invalid_ohlc": number,
        "dropped_incomplete_daily": number
      },
      "warnings": ["string"]
    }
  ]
}
```

**`scope=all&group=china` 返回 6 个指数**：
1. `000001.SS` 上证综指
2. `399001.SZ` 深证成指
3. `399006.SZ` 创业板指
4. `000688.SS` 科创50
5. `000300.SS` 沪深300
6. `000905.SS` 中证500

**注意**：前端 `parseIndices` 只取前 5 个（INDEX_ORDER），不包含中证500。

### 1.4 GET /markets/breadth

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.01s（缓存命中） |
| 是否依赖用户 | 否（公开接口） |

**完整响应结构**：
```json
{
  "source": "Sina Finance all A-share snapshot",
  "source_url": "https://...",
  "market_timestamp": null,
  "fetched_at": "ISO8601",
  "market_date": "YYYY-MM-DD",
  "is_stale": boolean,
  "cache_hit": boolean,
  "status": "available" | "unavailable",
  "scope": "all_a_shares_including_beijing",
  "coverage": {
    "expected": 5535,
    "returned": 5535,
    "valid_change": 5535,
    "coverage_ratio": 1.0,
    "node": "hs_a",
    "latest_tick_time": "HH:MM:SS"
  },
  "breadth": {
    "total": 5535,
    "advancers": 3349,
    "decliners": 2036,
    "unchanged": 150,
    "net_advancers": 1313,
    "advance_ratio": 0.6051,
    "decline_ratio": 0.3678,
    "unchanged_ratio": 0.0271,
    "state": "上涨家数占优",
    "classification_method": "string"
  },
  "turnover": {
    "status": "available",
    "currency": "CNY",
    "unit": "yuan",
    "total_amount_cny": 2023335485672,
    "total_amount_100m_cny": 20233.35,
    "amount_basis": {
      "raw_field": "string",
      "raw_unit": "string",
      "raw_total": number,
      "normalized_unit": "string",
      "normalized_total": number,
      "display_unit": "CNY_100m_yuan",
      "display_total": number,
      "scope": "string",
      "market_date": "string",
      "aggregation": "string"
    },
    "coverage": {
      "expected": 5535,
      "valid_amount": 5535,
      "coverage_ratio": 1.0,
      "exchange_sum_matches": true
    },
    "exchanges": {
      "shanghai": { "amount_cny": number, "amount_100m_cny": number, "valid_amount": number },
      "shenzhen": { "amount_cny": number, "amount_100m_cny": number, "valid_amount": number },
      "beijing": { "amount_cny": number, "amount_100m_cny": number, "valid_amount": number }
    },
    "interpretation": "string",
    "history_comparison": {
      "status": "intraday_not_comparable" | ...,
      "previous_market_date": null,
      "previous_total_amount_cny": null,
      "change_vs_previous_pct": null,
      ...
    }
  },
  "distribution": {
    "status": "available",
    "coverage": { "expected": 5535, "valid_change": 5535, "coverage_ratio": 1.0 },
    "median_pct_change": 0.647,
    "p25_pct_change": -0.69,
    "p75_pct_change": 2.905,
    "bins": {
      "strong_advancers_ge_3": 1338,
      "mild_advancers_gt_0_lt_3": 2011,
      "unchanged": 150,
      "mild_decliners_lt_0_gt_neg3": 1953,
      "strong_decliners_le_neg3": 83
    },
    "bin_ratios": { ... },
    "method": "string"
  },
  "warnings": ["string"]
}
```

**注意**：`exchange_breakdown` 字段**不存在**。前端 `parseBreadth` 不读取此字段。

### 1.5 GET /sectors/hot?limit=10

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.51s |
| 是否依赖用户 | 否（公开接口） |

**完整响应结构**：
```json
{
  "source": "Eastmoney A-share sector ranking",
  "source_url": "https://push2.eastmoney.com/...",
  "market_timestamp": "ISO8601",
  "fetched_at": "ISO8601",
  "is_stale": boolean,
  "cache_hit": boolean,
  "coverage": {
    "returned": 10,
    "total_available": 496,
    "ranking_field": "pct_change"
  },
  "warnings": ["string"],
  "sectors": [
    {
      "code": "BK1295",
      "name": "其他数字媒体",
      "latest": 917.47,
      "pct_change": 7.97,
      "main_net_inflow": 67474744.0,
      "advancers": 2,
      "decliners": 0,
      "unchanged": 0
    }
  ]
}
```

**关键发现**：
- `advance_ratio` 字段**不存在**于 sectors 数组元素中
- `advancers`/`decliners`/`unchanged` 来自东方财富，可能为 null（主源不可用时降级到新浪，新浪不提供此字段）
- 前端 `parseSectors` 不解析 `main_net_inflow`

### 1.6 GET /system/data-health

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.01s |
| 是否依赖用户 | 否（公开接口） |

**完整响应结构**：
```json
{
  "status": "healthy" | "attention" | "degraded",
  "user_label": "string",
  "created_at": "ISO8601",
  "summary": {
    "total": 67,
    "healthy": 0,
    "attention": 19,
    "critical": 48
  },
  "checks": [
    {
      "key": "market:china",
      "category": "market" | "fundamentals" | "information" | "reports" | "background",
      "status": "healthy" | "attention" | "critical",
      "label": "string",
      "is_open": boolean,
      "calendar_status": "string",
      "age_seconds": number | null,
      "market_timestamp": "string | null",
      ...
    }
  ],
  "method": "deterministic_data_health_audit_v1",
  "id": "uuid"
}
```

**check category 分布**（67 项）：
- market: 6
- fundamentals: 35
- information: 7
- reports: 4
- background: 15

**check status 分布**：
- critical: 48
- attention: 19
- healthy: 0

**check 额外字段集合**（不同 category 有不同字段）：
- market: is_open, calendar_status, calendar_coverage_end
- fundamentals: latest_report_date, age_seconds, market_timestamp, report_date, rows, dimensions, available, requested, requested_peers, ...
- information: events, media_events, official_events, ...
- reports: generated_at
- background: finished_at, started_at, poll_age_seconds, ...

### 1.7 GET /me/watchlist/brief

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.20s |
| 是否依赖用户 | 是（`require_session_user`） |

**新用户（空关注）响应**：
```json
{
  "type": "watchlist_brief",
  "generated_at": "ISO8601",
  "items": [],
  "coverage": {
    "requested": 0,
    "available": 0
  },
  "warnings": ["自选股为空。可先通过 POST /users/{id}/watchlist 添加。"]
}
```

**有数据时的 item 字段**：
- symbol, name, status, latest_change, metrics, current_quote, latest_bar, recent_bars, source, market_timestamp, fetched_at, is_stale, coverage, warnings

### 1.8 GET /me/research-actions

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.03s |
| 是否依赖用户 | 是（`require_session_user`） |

**新用户（无关注）响应**：
```json
{
  "type": "research_actions",
  "generated_at": "ISO8601",
  "method": "deterministic_research_action_board_v1",
  "items": [],
  "summary": {
    "symbols": 0,
    "triggered": 0,
    "pending_data": 0,
    "watching": 0,
    "priority_research": 0
  },
  "status_legend": {
    "triggered": "已有确定性证据达到复核条件",
    "pending_data": "当前资料仍缺少完成判断所需的证据",
    "watching": "条件尚未触发，继续按已定义变量观察"
  },
  "boundary": "string",
  "snapshot_id": "uuid",
  "snapshot_created_at": "ISO8601"
}
```

**有数据时的 item 字段**（来自 `_build_item`）：
- symbol, name, thesis, research_status, research_status_label, priority_score, data_as_of, latest_report_id, headline, actions[]
- actions[].id, actions[].action_type, actions[].category, actions[].title, actions[].status, actions[].severity, actions[].condition, actions[].current_evidence, actions[].next_step, actions[].checks

### 1.9 GET /me/research-changes?limit=20

| 属性 | 值 |
|---|---|
| HTTP 状态码 | 200 |
| 响应耗时 | 0.01s |
| 是否依赖用户 | 是（`require_session_user`） |

**新用户（无关注）响应**：
```json
{
  "type": "research_tracking",
  "generated_at": "ISO8601",
  "symbol": null,
  "items": [],
  "events": [],
  "coverage": {
    "requested": 0,
    "with_report": 0,
    "with_change_archive": 0
  },
  "method": "string",
  "boundary": "string"
}
```

**有数据时的字段**：
- items[].symbol, .name, .thesis, .in_watchlist, .latest_report_at, .latest_change, .current_state{...}, .next_review
- events[].id, .symbol, .event_type, .severity, .summary, .created_at, .data_as_of, .changes[], .new_evidence[], .current_state, .next_review, .boundary
- event_type 枚举："baseline", "evidence_change"
- severity 枚举："stable", "notice", "attention"

---

## 任务 2：字段合同

### 2.1 页面头部

| 字段 | 来源 | 路径 | 稳定？ |
|---|---|---|---|
| 当前交易状态 | /v1/today/overview | data.session.label | 是 |
| 交易状态 key | /v1/today/overview | data.session.key | 是 |
| 市场日期 | /v1/today/overview | data.summary.market_date | 是 |
| 最近更新时间 | /v1/today/overview | data.generated_at | 是 |
| 是否交易日 | /v1/today/overview | data.session.exchange_status === "open" | 是 |
| 市场本地时间 | /v1/today/overview | data.session.market_local_time | 是 |

### 2.2 五个指数

| 字段 | 后端字段 | 类型 | 缺失处理 |
|---|---|---|---|
| symbol | symbol | string | 不会缺失 |
| name | name | string | fallback 为 symbol |
| current/value | metrics.latest_close | number \| null | null 时显示"暂不可用" |
| change | metrics.return_1d_pct | number \| null | null 时显示"暂无" |
| market_timestamp | market_timestamp | string \| null | null 时隐藏时间 |
| source | source | string | 不会缺失 |
| is_stale | is_stale | boolean | false |

**注意**：后端不直接返回 `change` 字段，需要从 `metrics.return_1d_pct` 计算。`change_percent` 字段名**不存在**。

前端 `parseIndices` 只取 INDEX_ORDER 中的 5 个指数，忽略中证500。

### 2.3 市场结构

| 字段 | 后端路径 | 类型 | 缺失处理 |
|---|---|---|---|
| 上涨家数 | data.breadth.advancers | number \| null | null 时显示"暂无" |
| 下跌家数 | data.breadth.decliners | number \| null | null 时显示"暂无" |
| 平盘家数 | data.breadth.unchanged | number \| null | null 时显示"暂无" |
| 全市场总数 | data.breadth.total | number \| null | null 时显示"暂无" |
| 上涨比例 | data.breadth.advance_ratio | number \| null | null 时显示"暂无" |
| 成交额（亿元） | data.turnover.total_amount_100m_cny | number \| null | null 时显示"暂无可比数据" |
| 涨跌中位数 | data.distribution.median_pct_change | number \| null | null 时显示"暂无" |
| 市场状态描述 | data.breadth.state | string \| null | null 时显示"市场状态待确认" |
| 分布数组 | data.distribution.bins | object | 前端不使用 |

**不存在的字段**：涨停数、跌停数（无此数据）

### 2.4 热门行业

| 字段 | 后端字段 | 类型 | 缺失处理 |
|---|---|---|---|
| 行业名称 | name | string | 不会缺失 |
| 涨跌幅 | pct_change | number \| null | null 时显示"暂无" |
| 上涨家数 | advancers | number \| null | 可能为 null |
| 下跌家数 | decliners | number \| null | 可能为 null |
| 时间 | market_timestamp | string \| null | 可能为 null |
| 来源 | source | string | 不会缺失 |
| 缓存状态 | is_stale | boolean | false |

**注意**：
- `advance_ratio` 字段**不存在**于 sectors 响应中
- `main_net_inflow` 存在但前端不解析
- `unchanged` 存在但前端不解析
- 当主源（东方财富）不可用时，降级到新浪，新浪不提供 advancers/decliners

### 2.5 今日优先事项

**来源**：`/v1/today/overview` → data.priority_items

| 字段 | 后端字段 | 前端字段 | 类型 |
|---|---|---|---|
| 事项数组 | priority_items.items | overview.data.priorityItems | array |
| 每项 id | id | id | string |
| 每项 type | kind | kind | string |
| action.type | action.type | （前端未使用） | string |
| symbol | symbol | symbol | string \| null |
| title | title | title | string |
| detail | detail | detail | string \| null |
| status | status | （前端未直接使用） | string |
| status_label | status_label | statusLabel | string \| null |
| rank_reason | rank_reason | rankReason | string \| null |
| updated_at | updated_at | （前端未使用） | string \| null |

**所有枚举值**：
- kind: change_event, trade_review, observation_task, draft_confirmation, research_action
- category: change_event, trade_review, risk_review, user_task, draft_confirmation, evidence_gap, research_task
- action.type: open_change_event, open_trade_review, open_stock_tasks, open_stock_research
- status: pending, in_progress, waiting_data, ready, draft, triggered, pending_data, watching
- priority: high, normal, low

### 2.6 我的关注变化

**来源**：`/v1/today/overview` → data.personalized.changes 或 `/me/research-changes`

| 字段 | 后端字段 | 前端字段 | 类型 |
|---|---|---|---|
| symbol | symbol | symbol | string \| null |
| summary | summary | summary | string |
| severity | severity | severity | string \| null |
| data_as_of | data_as_of | dataAsOf | string \| null |
| created_at | created_at | (fallback to data_as_of) | string |

**research-changes 原始字段**（未经过 overview 聚合）：
- events[].id, .symbol, .event_type, .severity, .summary, .created_at, .data_as_of, .changes[], .new_evidence[], .current_state, .next_review, .boundary
- event_type: "baseline", "evidence_change"
- severity: "stable", "notice", "attention"

### 2.7 数据状态

**来源**：`/system/data-health`

| 字段 | 后端字段 | 前端字段 | 值 |
|---|---|---|---|
| 状态 | status | status | "healthy", "attention", "degraded" |
| 用户标签 | user_label | userLabel | "数据已连接", "部分数据同步中" |
| 检查时间 | created_at | createdAt | ISO8601 |
| 检查总数 | summary.total | summary.total | number |
| 正常数 | summary.healthy | summary.healthy | number |
| 关注数 | summary.attention | summary.attention | number |
| 关键数 | summary.critical | summary.critical | number |
| 可操作检查 | checks[] (status=critical|attention) | actionableChecks[] | array |
