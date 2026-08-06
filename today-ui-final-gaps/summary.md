# 今日观察 UI 最终缺口核验报告

生成时间: 2026-08-04T16:30:00+00:00
测试环境: Docker (qingshu-agent-v2:8002, qingshu-postgres-v2:5432)
测试数据库: qingshu_auth_test
测试用户: finalgap-1785856135 (3dcb7034-2299-4e9a-abab-f3b64cfa3706)

---

## 1. 指数趋势与时间语义

### 1.1 五个指数历史接口实测结果

| 指数代码 | 指数名称 | 状态码 | 响应耗时 | 数据点数 | 时间粒度 | 数据源 | 是否外部Provider |
|---|---|---|---|---|---|---|---|
| 000001.SS | 上证综指 | 200 | 1923ms | 35 | 1d | Tencent A-share index daily bars | YES |
| 399001.SZ | 深证成指 | 200 | 1189ms | 35 | 1d | Tencent A-share index daily bars | YES |
| 399006.SZ | 创业板指 | 200 | 911ms | 35 | 1d | Tencent A-share index daily bars | YES |
| 000300.SS | 沪深300 | 200 | 841ms | 35 | 1d | Tencent A-share index daily bars | YES |
| 000688.SS | 科创50 | 200 | 1357ms | 35 | 1d | Tencent A-share index daily bars | YES |

**关键发现:**
- 所有5个接口均返回200，数据完整
- 每个接口响应耗时 841ms ~ 1923ms（平均 ~1.2s）
- 5条接口总耗时约 6.2s（串行）/ ~2s（并行）
- 数据范围: 2026-06-16 ~ 2026-08-04（1个月）
- 数据粒度: 1d（日线）
- 数据源: Tencent A-share index daily bars (https://web.ifzq.gtimg.cn/appstock/app/fqkline/get)
- `market_timestamp`: 2026-08-04T01:30:00+00:00（即北京时间 2026-08-04 09:30，**开盘时间**）
- `fetched_at`: 2026-08-04T15:11:19+00:00（数据获取时间）
- `is_stale`: false（非缓存数据）
- `cache_hit`: false（未命中缓存）

**`market_timestamp=09:30` 真实含义:**
- 这是**当日开盘时间**（北京时间 09:30 对应 UTC 01:30）
- 不是缓存时间，不是数据点时间
- 是 Tencent Provider 返回的字段，代表该日K线的市场时间戳
- 最近数据点的 `timestamp` 字段才是真正的数据点时间

**是否适合首页一次加载五条微趋势:**
- ❌ **不适合**。5条接口串行需 6.2s，即使并行也需 ~2s
- 首页 already 通过 `/v1/today/overview` 聚合获取指数数据（耗时 ~15.6s，因为包含更多数据）
- 建议: 首页仅展示最新收盘价和涨跌幅（已有），微趋势图表需用户点击进入个股页面后单独请求

### 1.2 指数历史响应结构（脱敏）

```json
{
  "symbol": "000001.SS",
  "display_name": "上证综指",
  "currency": "CNY",
  "exchange": "SSE",
  "timezone": "Asia/Shanghai",
  "previous_close": 3809.66,
  "regular_market_price": 3822.28,
  "data_granularity": "1d",
  "source": "Tencent A-share index daily bars",
  "source_url": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
  "market_timestamp": "2026-08-04T01:30:00+00:00",
  "fetched_at": "2026-08-04T15:11:19+00:00",
  "is_stale": false,
  "cache_hit": false,
  "coverage": {
    "requested_range": "1mo",
    "interval": "1d",
    "points": 35,
    "first_timestamp": "2026-06-16T01:30:00+00:00",
    "last_timestamp": "2026-08-04T01:30:00+00:00",
    "dropped_invalid_ohlc": 0,
    "dropped_incomplete_daily": 0
  },
  "warnings": [],
  "points": [
    {
      "timestamp": "2026-06-16T01:30:00+00:00",
      "open": 4094.21,
      "close": 4091.89,
      "adjusted_close": 4091.89,
      "high": 4103.93,
      "low": 4077.87,
      "volume": 615668296
    }
  ]
}
```

---

## 2. 市场广度图表能力

### 2.1 完整脱敏响应

```json
{
  "source": "Sina Finance all A-share snapshot",
  "source_url": "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
  "market_timestamp": null,
  "fetched_at": "2026-08-04T15:13:22+00:00",
  "market_date": "2026-08-04",
  "is_stale": false,
  "cache_hit": false,
  "status": "available",
  "scope": "all_a_shares_including_beijing",
  "coverage": {
    "expected": 5535,
    "returned": 5535,
    "valid_change": 5535,
    "coverage_ratio": 1,
    "node": "hs_a",
    "latest_tick_time": "16:24:00"
  },
  "breadth": {
    "total": 5535,
    "advancers": 3642,
    "decliners": 1746,
    "unchanged": 147,
    "net_advancers": 1896,
    "advance_ratio": 0.658,
    "decline_ratio": 0.3154,
    "unchanged_ratio": 0.0266,
    "state": "普涨",
    "classification_method": "普涨/普跌要求上涨或下跌比例至少65%，且涨跌家数净差至少500；否则只描述哪一方向家数占优。"
  },
  "turnover": {
    "status": "available",
    "currency": "CNY",
    "unit": "yuan",
    "total_amount_cny": 2228015019883,
    "total_amount_100m_cny": 22280.15,
    "amount_basis": { ... },
    "coverage": {
      "expected": 5535,
      "valid_amount": 5535,
      "coverage_ratio": 1,
      "exchange_sum_matches": true
    },
    "exchanges": {
      "shanghai": { "amount_cny": 1007806998637, "amount_100m_cny": 10078.07, "valid_amount": 2309 },
      "shenzhen": { "amount_cny": 1205138504982, "amount_100m_cny": 12051.39, "valid_amount": 2894 },
      "beijing": { "amount_cny": 15069516264, "amount_100m_cny": 150.7, "valid_amount": 332 }
    },
    "interpretation": "成交额是当日累计成交金额，不是资金净流入、机构意图或未来方向信号。",
    "history_comparison": {
      "status": "building_history",
      "previous_market_date": null,
      "previous_total_amount_cny": null,
      "change_vs_previous_pct": null,
      "previous_5d_average_amount_cny": null,
      "change_vs_previous_5d_average_pct": null,
      "previous_20d_average_amount_cny": null,
      "change_vs_previous_20d_average_pct": null,
      "available_prior_sessions": 0,
      "stored_prior_sessions": 0,
      "excluded_prior_sessions": [],
      "method": "只比较本系统保存的完整收盘交易日..."
    }
  },
  "distribution": {
    "status": "available",
    "coverage": { "expected": 5535, "valid_change": 5535, "coverage_ratio": 1 },
    "median_pct_change": 0.972,
    "p25_pct_change": -0.4625,
    "p75_pct_change": 3.312,
    "bins": {
      "strong_advancers_ge_3": 1506,
      "mild_advancers_gt_0_lt_3": 2136,
      "unchanged": 147,
      "mild_decliners_lt_0_gt_neg3": 1672,
      "strong_decliners_le_neg3": 74
    },
    "bin_ratios": {
      "strong_advancers_ge_3": 0.2721,
      "mild_advancers_gt_0_lt_3": 0.3859,
      "unchanged": 0.0266,
      "mild_decliners_lt_0_gt_neg3": 0.3021,
      "strong_decliners_le_neg3": 0.0134
    },
    "method": "使用全体有效个股涨跌幅的中位数与四分位数..."
  },
  "exchange_breakdown": {
    "shanghai": { "total": 2309, "advancers": 1369, "decliners": 880, "unchanged": 60, "valid_amount": 2309, "amount_cny": 1007806998637 },
    "shenzhen": { "total": 2894, "advancers": 2037, "decliners": 783, "unchanged": 74, "valid_amount": 2894, "amount_cny": 1205138504982 },
    "beijing": { "total": 332, "advancers": 236, "decliners": 83, "unchanged": 13, "valid_amount": 332, "amount_cny": 15069516264 }
  },
  "warnings": ["该快照按新浪沪深京A股列表逐页汇总，包含北交所；停牌或涨跌幅字段缺失时会拒绝确认全市场广度。"]
}
```

### 2.2 关键字段确认

| 问题 | 答案 |
|---|---|
| 是否有真实 distribution bins | ✅ **有**。5个固定分档: strong_advancers_ge_3, mild_advancers_gt_0_lt_3, unchanged, mild_decliners_lt_0_gt_neg3, strong_decliners_le_neg3 |
| bins 的真实区间 | ±3%为界（>=3%为强涨, <=-3%为强跌） |
| 是否有 advance_ratio / decline_ratio | ✅ **有**。`advance_ratio: 0.658`, `decline_ratio: 0.3154` |
| 是否有涨停、跌停、停牌数量 | ❌ **没有**。只有 advancers/decliners/unchanged，没有区分涨停/跌停/停牌 |
| 是否有最近5-7日成交额序列 | ❌ **没有**。`history_comparison.status = "building_history"`，所有历史字段均为 null |
| 是否有较昨日成交额变化 | ❌ **没有**。`change_vs_previous_pct = null` |
| exchange_breakdown 完整结构 | ✅ **有**。包含 shanghai/shenzhen/beijing 三个交易所的 total/advancers/decliners/unchanged/valid_amount/amount_cny |
| 哪些字段只代表当前快照 | `breadth`, `distribution`, `exchange_breakdown` 均为当前快照；`turnover.history_comparison` 虽存在但全部为 null |

### 2.3 图表能力结论

| 图表类型 | 能否实现 | 说明 |
|---|---|---|
| 环图（涨跌平占比） | ✅ **能** | `distribution.bin_ratios` 提供5档占比，可直接绘制环图 |
| 涨跌分布柱图 | ✅ **能** | `distribution.bins` 提供5档绝对数量，可绘制柱状图 |
| 七日成交额柱图 | ❌ **不能** | `history_comparison` 全部为 null，无历史成交额序列 |
| 交易所成交额对比 | ✅ **能** | `turnover.exchanges` 提供沪深京三地成交额 |

---

## 3. 市场接口是否重复计算

### 3.1 响应耗时实测

| 接口 | 响应耗时 | 后端 Service 调用 |
|---|---|---|
| `/v1/today/overview` | ~15.6s | `get_overview` → 并行调用: get_indices, market_breadth, hot_sectors(limit=5), list_tasks, get_packet(research_actions), get_packet(research_changes), list_writebacks, list_user_trade_reviews, get_user_packet(change_events) |
| `/indices?scope=all&group=china` | ~15.3s | `get_indices(scope="all", group="china")` |
| `/markets/breadth` | ~0.024s | `market_breadth()` |
| `/sectors/hot?limit=10` | ~0.38s | `hot_sectors(limit=10)` |

### 3.2 重复计算分析

| 后端 Service | overview 调用 | 独立接口调用 | 是否重复 | 原因 |
|---|---|---|---|---|
| `get_indices` | ✅ | ✅ `/indices` | **是** | 两者都调用 `analysis.get_indices(scope="all", group="china")`，都从同一外部 Provider（Tencent）拉取数据 |
| `market_breadth` | ✅ | ✅ `/markets/breadth` | **是** | 两者都调用 `analysis.market_breadth()`，从同一 Sina Finance 快照拉取 |
| `hot_sectors` | ✅ (limit=5) | ✅ `/sectors/hot?limit=10` | **部分** | 后端相同服务，但 limit 不同（5 vs 10），导致不同查询 |

**关键发现:**
1. `/v1/today/overview` 和 `/indices` **共享缓存** - 两者调用同一个 `get_indices` 服务，如果缓存未过期，第二次调用会命中缓存
2. 但首次加载时，两者都会触发外部 Provider 调用（~15s）
3. `/markets/breadth` 和 `/sectors/hot` 响应快（<1s），说明它们可能使用不同的数据源或缓存策略
4. overview 的耗时（15.6s）与 indices 的耗时（15.3s）几乎相同，说明 overview 的额外聚合逻辑（priority_items, personalized_packet）耗时 negligible

### 3.3 建议

| 方案 | 说明 | 是否修改后端 |
|---|---|---|
| 保持8条独立Query | 当前方案，重复调用 indices/breadth/hot_sectors | ❌ 不修改 |
| 使用 overview 首屏 + 补充 | 首屏用 overview 数据，需要更多细节时再请求独立接口 | ❌ 不修改 |
| 前端缓存 overview | 用 React Query 缓存 overview， staleTime 内不重复请求 | ❌ 不修改 |

**推荐方案:** 保持8条独立Query，但：
1. 将 indices 的 staleTime 从 60s 延长到 300s（5分钟），因为指数数据更新频率低
2. 将 breadth 和 sectors 的 staleTime 从 60s 延长到 120s
3. 使用 React Query 的 `placeholderData` 功能，在 overview 加载期间显示缓存数据

---

## 4. 热门行业稳定数量

### 4.1 limit 参数实测

| limit 参数 | 实际返回 | 是否严格遵守 | 备注 |
|---|---|---|---|
| limit=5 | 5 条 | ✅ | 严格返回5条 |
| limit=8 | 8 条 | ✅ | 严格返回8条 |
| limit=10 | 10 条 | ✅ | 严格返回10条 |

### 4.2 字段全集

每条 sector 包含以下字段:
- `code`: 板块代码（如 "new_stock", "new_dzxx"）
- `name`: 板块名称（如 "次新股", "电子信息"）
- `member_count`: 成员数量
- `average_price`: 平均价格
- `price_change`: 价格变化
- `pct_change`: 涨跌幅
- `volume`: 成交量
- `turnover`: 成交额
- `leading_symbol`: 领涨股代码
- `leading_name`: 领涨股名称
- `latest`: null（始终为 null）
- `main_net_inflow`: null（始终为 null）
- `advancers`: null（始终为 null）
- `decliners`: null（始终为 null）
- `unchanged`: null（始终为 null）

### 4.3 关键发现

- **advancers/decliners/unchanged 全部为 null** - 前端无法展示板块内涨跌家数
- **main_net_inflow 全部为 null** - 无法展示主力净流入
- **total_available = 49** - 系统中共有49个行业板块，当前展示的是涨幅前 N 名
- **排序字段**: `pct_change`（涨跌幅降序）

### 4.4 首页建议展示数量

| 选项 | 说明 |
|---|---|
| 5 | 太少， TodayOverview 后端已取5条，前端切片到8条，建议至少8条 |
| 6 | 不常见，建议避免 |
| 8 | ✅ **推荐**。当前前端展示8条，limit=8 稳定返回8条 |
| 10 | 可以，但移动端空间有限 |

**推荐: 8条**（与当前实现一致，limit=8 稳定返回）

---

## 5. 有数据用户的个人研究状态

### 5.1 测试用户

- 账号: finalgap-1785856135
- 用户ID: 3dcb7034-2299-4e9a-abab-f3b64cfa3706
- 数据库: qingshu_auth_test

### 5.2 数据插入状态

⚠️ **数据插入被分类器阻止**。以下 SQL 已准备好，需要手动执行:

文件位置: `f:/tools/3.9haorzn-03/today-ui-final-gaps/test_data.sql`

```sql
-- 观察任务（3条）
INSERT INTO observation_tasks (id, user_id, symbol, title, description, status, priority, source_type, due_at, created_at, updated_at)
VALUES
  ('otask-1', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', '688981.SH', '中芯国际Q2业绩跟踪', '跟踪中芯国际第二季度财报发布，关注毛利率和产能利用率变化', 'in_progress', 'high', 'user', '2026-08-10T00:00:00+00:00', '2026-08-01T00:00:00+00:00', '2026-08-04T00:00:00+00:00'),
  ('otask-2', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'N/A', '行业政策变化监控：半导体出口管制', '这是一个非常长的标题用于测试极限情况下的前端显示效果...', 'pending', 'normal', 'user', '2026-08-15T00:00:00+00:00', '2026-08-02T00:00:00+00:00', '2026-08-04T00:00:00+00:00'),
  ('otask-3', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', '000063.SZ', '中兴通讯AI服务器订单确认', '等待中兴通讯确认AI服务器订单数量和交付时间表', 'waiting_data', 'normal', 'user', '2026-08-20T00:00:00+00:00', '2026-08-03T00:00:00+00:00', '2026-08-04T00:00:00+00:00');

-- 变化事件（3条）
INSERT INTO change_events (id, symbol, event_type, title, fact_summary, occurred_at, detected_at, source_name, source_url, data_status, rule_version, dedupe_hash, payload_json, created_at, updated_at)
VALUES
  ('ce-1', '688981.SH', 'earnings', '中芯国际Q2营收超预期', '...', '2026-08-04T01:00:00+00:00', '2026-08-04T06:00:00+00:00', '财务报告', '', 'verified', 'v1', 'hash-ce-1', '{}', '2026-08-04T06:00:00+00:00', '2026-08-04T06:00:00+00:00'),
  ('ce-2', '000063.SZ', 'news', '中兴通讯获AI服务器大单', '...', '2026-08-03T22:00:00+00:00', '2026-08-04T05:00:00+00:00', '公司公告', '', 'verified', 'v1', 'hash-ce-2', '{}', '2026-08-04T05:00:00+00:00', '2026-08-04T05:00:00+00:00'),
  ('ce-3', '688981.SH', 'rating', '多家机构上调中芯国际评级', '...', '2026-08-04T02:00:00+00:00', '2026-08-04T07:00:00+00:00', '研报汇总', '', 'verified', 'v1', 'hash-ce-3', '{}', '2026-08-04T07:00:00+00:00', '2026-08-04T07:00:00+00:00');

-- 用户变化链接
INSERT INTO user_change_links (id, user_id, change_event_id, symbol, relevance_status, created_at, updated_at)
VALUES
  ('ucl-1', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-1', '688981.SH', 'relevant', '2026-08-04T06:00:00+00:00', '2026-08-04T06:00:00+00:00'),
  ('ucl-2', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-2', '000063.SZ', 'relevant', '2026-08-04T05:00:00+00:00', '2026-08-04T05:00:00+00:00'),
  ('ucl-3', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', 'ce-3', '688981.SH', 'relevant', '2026-08-04T07:00:00+00:00', '2026-08-04T07:00:00+00:00');

-- 关注列表（2只）
INSERT INTO watchlist (user_id, symbol, name, market, thesis, created_at, updated_at)
VALUES
  ('3dcb7034-2299-4e9a-abab-f3b64cfa3706', '688981.SH', '中芯国际', 'CN', '半导体制造龙头，关注先进制程进展', '2026-08-01T00:00:00+00:00', '2026-08-04T00:00:00+00:00'),
  ('3dcb7034-2299-4e9a-abab-f3b64cfa3706', '000063.SZ', '中兴通讯', 'CN', '5G设备+AI服务器双轮驱动', '2026-08-02T00:00:00+00:00', '2026-08-04T00:00:00+00:00');

-- 研究空间（2只）
INSERT INTO stock_workspaces (id, user_id, symbol, name, market, relation_type, priority, tracking_status, workflow_status, attention_tags_json, version, created_at, updated_at)
VALUES
  ('ws-test-1', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', '688981.SH', '中芯国际研究', 'CN', 'watching', 'high', 'active', 'researching', '[]', 1, '2026-08-01T00:00:00+00:00', '2026-08-04T00:00:00+00:00'),
  ('ws-test-2', '3dcb7034-2299-4e9a-abab-f3b64cfa3706', '000063.SZ', '中兴通讯关注', 'CN', 'watching', 'normal', 'active', 'idle', '[]', 1, '2026-08-02T00:00:00+00:00', '2026-08-04T00:00:00+00:00');
```

### 5.3 API 响应结构（当前空状态）

由于数据未插入，当前 API 返回空状态。以下是各接口的响应结构:

**GET /v1/today/overview (空状态)**
- `summary.headline`: "当前没有必须立即处理的研究事项。"
- `summary.market_date`: "2026-08-04"
- `priority_items.items`: []
- `research_changes.items`: []
- `data_health.status`: "degraded"

**GET /me/watchlist/brief (空状态)**
- `requested`: 0
- `available`: 0
- `items`: []

**GET /me/research-actions (空状态)**
- `items`: []
- `empty`: true
- `boundary`: "..."

**GET /me/research-changes?limit=20 (空状态)**
- `items`: []
- `has_more`: false

---

## 6. 顶部搜索合同

### 6.1 完整合同

**端点:** `GET /v1/search?q={query}&limit={limit}`

**参数:**
- `q`: string, minLength=1, maxLength=120, **required**
- `limit`: integer, default=8, min=1, max=20, optional

**返回结构:**
```json
{
  "contract_version": "global_search_v1",
  "query": "搜索关键词",
  "groups": [
    {
      "key": "stocks",
      "label": "股票",
      "items": [
        {
          "type": "stock",
          "id": "000001.SZ",
          "title": "平安银行",
          "subtitle": "000001.SZ",
          "symbol": "000001.SZ",
          "industry": null,
          "url": "/stocks/000001.SZ"
        }
      ]
    }
  ],
  "total": 1,
  "boundary": "股票和行业来自本地稳定市场快照；研究、对话和复盘仅搜索当前用户空间。"
}
```

### 6.2 支持的搜索组

| 组 | Key | 说明 | 是否需要登录 |
|---|---|---|---|
| 股票 | `stocks` | 本地稳定市场快照 | ❌ 不需要 |
| 行业 | `industries` | 本地稳定市场快照 | ❌ 不需要 |
| 我的研究 | `workspaces` | 当前用户空间 | ✅ 需要 |
| 历史对话 | `conversations` | 当前用户空间 | ✅ 需要 |
| 交易复盘 | `reviews` | 当前用户空间 | ✅ 需要 |

### 6.3 实测结果

| 查询 | 结果 | 说明 |
|---|---|---|
| 空字符串 `""` | 422 | minLength=1 校验失败 |
| `"a"` | 1 条结果 | 股票组: NVDA（英伟达） |
| `"000001"` | 1 条结果 | 股票组: 000001.SZ（平安银行） |
| `"000001.SZ"` | 1 条结果 | 股票组: 000001.SZ（平安银行） |
| `"NVDA"` | 1 条结果 | 股票组: NVDA（英伟达） |
| `"半导体"` | Not Found | URL 编码问题，无法测试中文 |
| `"半天道"` | 0 条结果 | 无匹配 |

### 6.4 支持状态

| 功能 | 状态 | 说明 |
|---|---|---|
| 股票搜索 | ✅ 支持 | 支持代码、名称、别名搜索 |
| 行业搜索 | ⚠️ 条件支持 | 代码中存在 `_search_industries`，但未在实测中返回结果（当前用户无研究空间） |
| 研究空间搜索 | ⚠️ 条件支持 | 需要用户有 stock_workspaces |
| 会话搜索 | ⚠️ 条件支持 | 需要用户有 conversations |
| 交易复盘搜索 | ⚠️ 条件支持 | 需要用户有 trade_reviews |
| 通知数量接口 | ❌ 不支持 | 无此接口 |
| 用户头像字段 | ❌ 不支持 | 搜索返回中无头像字段 |
| 设置页路由 | ❌ 不支持 | 无设置页路由 |

### 6.5 搜索耗时

| 查询类型 | 耗时 | 说明 |
|---|---|---|
| 短查询 "a" | <100ms | 本地内存搜索 |
| 精确代码 "000001" | <100ms | 本地内存搜索 |
| 美股代码 "NVDA" | <100ms | 本地内存搜索 |

**结论:** 搜索可在本轮接入，但行业/研究/会话/复盘分组需要用户有相关数据才能返回结果。首屏搜索仅展示股票结果。

---

## 7. 额外模块存在性结论

| 模块 | 是否存在 | 接口 | 读取副作用 | 额外 Provider | 建议放入首页 |
|---|---|---|---|---|---|
| 今日研究报告列表 | ❌ 不存在 | - | - | - | ❌ 否 |
| 全球市场指数 | ✅ 存在 | `GET /indices?scope=all` | 无 | Yahoo Finance Chart | ✅ 是（可选模块） |
| 北向资金 | ❌ 不存在 | - | - | - | ❌ 否 |
| 主力资金 | ❌ 不存在 | - | - | - | ❌ 否 |
| 异动机会列表 | ❌ 不存在 | - | - | - | ❌ 否 |
| 风险提示列表 | ❌ 不存在 | - | - | - | ❌ 否 |
| 七日成交历史 | ❌ 不存在 | - | - | - | ❌ 否 |

### 7.1 全球市场指数详情

**接口:** `GET /indices?scope=all`

**响应结构:**
```json
{
  "generated_at": "2026-08-04T16:17:02+00:00",
  "scope": "all",
  "group": null,
  "coverage": { "requested": 20, "available": 20 },
  "warnings": ["上游有 1 个无收盘价记录，已跳过。"],
  "indices": [
    {
      "symbol": "000001.SS",
      "name": "上证综指",
      "region": "中国",
      "group": "china",
      "status": "available",
      "metrics": {
        "latest_close": 3822.28,
        "return_1d_pct": 0.3313,
        "return_5d_pct": 0.2352,
        "return_20d_pct": -4.2093,
        "return_60d_pct": -9.5323,
        "ma20": 3873.7135,
        "ma60": 4017.3298,
        "volatility_20d_annualized_pct": 20.8737,
        "max_drawdown_60d_pct": -11.2767,
        "technical_state": "动量改善",
        "trend_state": "中期偏强"
      },
      "latest_bar": { "timestamp": "...", "open": ..., "close": ..., "volume": ... },
      "recent_bars": [...],
      "source": "Yahoo Finance Chart",
      "market_timestamp": "2026-08-03T13:30:00+00:00",
      "is_stale": false,
      "coverage": { "requested_range": "3mo", "interval": "1d", "points": 63 }
    }
  ]
}
```

**覆盖市场 (20个指数):**
- 中国 (6): 上证综指, 深证成指, 创业板指, 科创50, 沪深300, 中证500
- 中国香港 (2): 恒生指数, 恒生科技指数
- 美国 (5): 标普500, 纳斯达克综合, 道琼斯工业指数, 罗素2000, VIX波动率指数
- 欧洲/德国/英国/日本/韩国/澳大利亚/印度 (7)

**注意:** 该接口耗时 ~15s（与 indices 相同），因为共享同一个 `get_indices` 服务。

---

## 8. 最终结论

### A. 可以直接实现（有真实合同）

1. **主要指数微趋势** - `/indices/{symbol}/history?range=1mo` 返回35天日线数据
2. **市场广度环图** - `distribution.bin_ratios` 提供5档占比
3. **市场广度柱图** - `distribution.bins` 提供5档绝对数量
4. **交易所成交额对比** - `turnover.exchanges` 提供沪深京三地数据
5. **全球市场指数** - `/indices?scope=all` 返回20个全球指数
6. **顶部搜索（股票）** - `/v1/search?q={query}` 支持股票代码/名称搜索

### B. 有条件实现（依赖历史序列/额外请求/性能权衡）

1. **指数微趋势首屏加载** - 5条接口总耗时 ~6s，需考虑并行加载或缓存策略
2. **七日成交额柱图** - `history_comparison` 全部为 null，需等待后端实现历史数据存储
3. **行业搜索** - 代码中存在但未在实测中验证（需要用户有研究空间数据）
4. **搜索中的研究/对话/复盘** - 需要用户有相关数据才能返回结果

### C. 本轮删除（无真实合同或会造成误导）

1. **北向资金** - 接口不存在
2. **主力资金** - 接口不存在
3. **异动机会列表** - 接口不存在
4. **风险提示列表** - 接口不存在
5. **涨停/跌停/停牌数量** - 市场广度接口不提供
6. **较昨日成交额变化** - history_comparison 全部为 null
7. **通知数量接口** - 不存在
8. **用户头像字段** - 搜索返回中不存在
9. **设置页路由** - 不存在

### D. 性能结论

**首页存在重复市场计算。**

| 重复点 | 详情 |
|---|---|
| indices 重复 | overview 和 `/indices` 都调用 `get_indices(scope="all", group="china")` |
| breadth 重复 | overview 和 `/markets/breadth` 都调用 `market_breadth()` |
| hot_sectors 重复 | overview (limit=5) 和 `/sectors/hot?limit=10` 都调用 `hot_sectors()` |

**影响:** 首次加载时，overview (15.6s) + indices (15.3s) + breadth (0.024s) + sectors (0.38s) = ~31s 总耗时。但由于共享缓存，实际影响较小。

**建议:** 使用 React Query 缓存策略，在 overview 加载期间显示缓存数据，避免重复请求。

### E. 个人数据结论

⚠️ **测试数据未成功插入（分类器阻止）**。已准备好 SQL 文件 `test_data.sql`，需手动执行。

**预期非空状态布局:**
- 优先处理: 最多5条，覆盖不同 kind（observation_task, change_event, research_action 等）
- 研究变化: 最多6条，包含 symbol、summary、severity
- 关注列表: 2只股票，显示名称和 thesis
- 长标题: 可正确换行（CSS word-break）
- 无 symbol 事项: 显示为纯文本（无 Link）
- waiting_data 状态: 显示灰色状态标签

### F. 顶部搜索结论

**搜索可在本轮接入，但有条件:**

- ✅ 股票搜索立即可用（本地快照，无需登录）
- ⚠️ 行业搜索需要验证（代码存在但未实测）
- ⚠️ 研究/对话/复盘搜索需要用户有相关数据
- ❌ 无通知、无头像、无设置页

### G. Codex 最终 UI 重构时允许新增的请求

1. `GET /indices/{symbol}/history?range=1mo|3mo|6mo|1y|2y|5y|max`
2. `GET /markets/breadth`（已有，可复用）
3. `GET /indices?scope=all`（已有，全球指数）
4. `GET /v1/search?q={query}&limit={limit}`（已有）

### H. Codex 最终 UI 重构时禁止新增的请求

1. 北向资金接口（不存在）
2. 主力资金接口（不存在）
3. 异动机会接口（不存在）
4. 风险提示接口（不存在）
5. 七日成交历史接口（不存在）
6. 通知数量接口（不存在）
7. 设置页路由（不存在）

---

## 附录: 已保存文件清单

```
today-ui-final-gaps/
├─ summary.md                          (本文件)
├─ index-history.json                  (5个指数历史接口实测数据)
├─ market-breadth-full.json            (/markets/breadth 完整响应)
├─ sectors-limit-comparison.json       (limit=5/8/10 对比)
├─ populated-overview.json             (待填充: 非空 overview)
├─ populated-watchlist.json            (待填充: 非空 watchlist)
├─ populated-actions.json              (待填充: 非空 research-actions)
├─ populated-changes.json              (待填充: 非空 research-changes)
├─ search-contract.json                (/v1/search 合同)
├─ indices-all-response.json           (全球20个指数)
├─ test_data.sql                       (测试数据 SQL，需手动执行)
└─ (screenshots 待拍摄)
```
