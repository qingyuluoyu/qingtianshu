# 关注、持仓、交易与复盘闭环设计

## 目标

修复“我的关注”与“个人复盘”之间的数据断链，使用户能够从关注股票明确创建模拟或实盘持仓、记录成交，并由后端确定性计算持仓与复盘口径。关注、研究、持仓和交易保持独立，不再用一个状态字段互相覆盖。

## 范围

本轮包含：

- 独立的关注、持仓和成交接口契约。
- 持仓与成交的用户资源权限、幂等和并发版本控制。
- 服务端持仓成本、已实现盈亏、未实现盈亏、费用和胜率计算。
- 关注页到持仓/成交的明确入口。
- 个人复盘读取真实持仓与成交账本。
- 会话失效时停止静默创建新用户。
- 旧 `watchlist` 交易字段的只读兼容和安全迁移标记。

本轮不包含券商连接、自动交易、正式税费配置中心或历史券商流水导入。

## 领域边界

### WatchlistItem

关注对象只表达研究意图：

- `priority`: `high | normal | low`
- `reason`
- `catalyst_condition`
- `invalidation_condition`
- `tracking_frequency`
- `tracking_status`: `active | paused`

买入价、卖出价、持仓数量和清仓状态不属于关注对象。

### Position

持仓对象表达用户当前或历史持仓：

- `account_type`: `simulated | live`
- `status`: `open | closed`
- `quantity`
- `cost_price`
- `current_price`
- `data_as_of`
- `version`

Position 是成交账本的投影。用户不能直接提交已实现盈亏。

### Trade

成交是不可变账本事实：

- `side`: `buy | sell`
- `executed_at`
- `price`
- `quantity`
- `fee`
- `idempotency_key`

卖出数量不得超过持仓数量。成交必须属于当前用户的 Position，证券代码必须与 Position 一致。

### Review

复盘由 Position 和 Trade 确定性生成：

- 已平仓交易只统计导致持仓数量归零的完整平仓事件。
- 部分卖出计入已实现盈亏，但不计入平仓胜率。
- 未实现盈亏只来自开放持仓。
- 净盈亏等于已实现盈亏加未实现盈亏减显式费用。
- 当前价缺失时未实现盈亏为空，不用零值代替。

## 金融计算

本轮采用移动加权平均成本：

1. 买入前持仓数量为 `Q`、成本为 `C`，新增成交数量为 `q`、价格为 `p`。
2. 新成本为 `(Q × C + q × p) / (Q + q)`。
3. 卖出不改变剩余持仓单位成本。
4. 卖出毛已实现盈亏为 `(卖出价 - 当前单位成本) × 卖出数量`。
5. 交易费用作为独立字段累计，避免调用方传入的盈亏口径不明。

方法版本固定为 `moving_weighted_average_v1`。本轮费用由用户记录的成交费用提供，不虚构佣金、印花税或过户费。

## API 设计

### 关注

- `GET /api/v1/me/watchlist`
- `POST /api/v1/me/watchlist`
- `PATCH /api/v1/me/watchlist/{symbol}`
- `DELETE /api/v1/me/watchlist/{symbol}`

列表投影额外返回独立的 `research_status` 和 `position_status`，但不把它们保存为关注状态。

旧 `/me/watchlist` 保留兼容，停止接受新的买入价、持仓数量和卖出价写入；旧字段只在兼容响应中标记为 `legacy_position_hint`。

### 持仓与成交

- `GET /api/v1/me/positions`
- `POST /api/v1/me/positions`
- `GET /api/v1/me/positions/{position_id}`
- `POST /api/v1/me/positions/{position_id}/trades`

创建 Position 时同时记录首笔买入成交，整个操作使用数据库事务。请求包含 `idempotency_key`。记录成交时包含 `base_version`，版本冲突返回 409。

### 复盘

- `GET /api/v1/me/trade-reviews`

旧 `/me/trade-reviews` 保留为兼容别名，返回同一服务结果。

## 数据库演进

采用 expand-migrate-contract：

1. 新增 `positions.version`、`positions.method_version`、`trades.idempotency_key`、`trades.position_closed`。
2. 新增用户范围内的成交幂等唯一约束。
3. 不删除旧 `watchlist` 字段。
4. 旧关注记录中存在买入价和数量时，只返回 `legacy_position_hint`，不自动生成真实持仓，避免伪造成交时间、费用和成本来源。
5. 用户确认后通过正式创建持仓接口迁移。

## 会话行为

前端只有在明确的首次体验入口中才能创建用户。普通页面收到 401 时显示“会话已失效，请重新登录”，不得因网络错误、500 或数据库错误创建新用户。

## 错误处理

- 非 A 股证券：422。
- Position 不存在或不属于当前用户：404。
- `base_version` 冲突：409。
- 卖出数量超过持仓：422。
- 已关闭持仓继续成交：409。
- 幂等键重复且请求相同：返回原结果。
- 幂等键重复但负载不同：409。
- 当前价缺失：保留持仓，未实现盈亏返回 `null` 并给出数据状态。

## 前端行为

- 添加关注表单只保留股票、关注理由、优先级、催化条件、失效条件和跟踪频率。
- 关注列表分别展示关注、研究和持仓状态。
- 每行提供“转为模拟持仓”和“记录实盘持仓”入口。
- 持仓录入要求数量、成本价、成交时间、费用和幂等键。
- 复盘页展示当前持仓、成交历史、已实现/未实现盈亏、费用、净盈亏和完整平仓胜率。
- 旧字段存在时显示“发现历史持仓线索，待确认迁移”，不纳入复盘计算。

## 验证

- 单元测试覆盖移动加权成本、部分卖出、完整平仓、超卖、费用和缺失当前价。
- API 测试覆盖用户隔离、幂等、版本冲突、非法市场和旧接口兼容。
- 垂直链路测试覆盖关注 → 创建持仓 → 买卖成交 → 复盘。
- 前端契约测试确保关注表单不再提交旧交易字段，401 不再创建用户。
- 运行受影响测试、完整 API 测试、完整非 API 测试、Python 编译和 JavaScript 语法检查。

## 回滚

本轮数据库变更为纯新增。旧接口保留兼容，因此代码可以回滚；新写入的 Position 和 Trade 仍能被旧版复盘读取。若前端回滚，新增接口不会影响旧关注读取。数据库新增列和索引不在同一发布中删除。
