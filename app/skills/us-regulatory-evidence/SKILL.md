---
name: us-regulatory-evidence
description: 使用 SEC 官方财务事实和监管文件研究美股公司，严格区分申报事实、媒体报道与估值快照。
version: 0.1.0
metadata:
  hermes:
    tags: [finance, sec, edgar, filings, us-equity]
---

# US Regulatory Evidence

## 目标

让美股研究优先建立在 SEC 官方申报和可追溯监管文件上，不让媒体标题替代公司事实。

## 必须遵守

1. `fundamentals.regulatory_filings` 中的 10-Q、10-K、8-K 是官方监管文件线索，结论应优先引用其标题、日期与原文链接。
2. `financial_periods` 来自 SEC Companyfacts 的 XBRL 结构化事实；10-Q 按财政年度累计口径、10-K 按完整财政年度口径解释。
3. 同比值只允许使用确定性解析器已计算的 `revenue_yoy_pct` 与 `net_profit_yoy_pct`，不得自行选择比较期或补算。
4. 腾讯美股估值只提供市场快照；固定同行样本也不是完整行业分位，PE、PB、市值不能在缺少历史分位和业务结构校准时写成高估或低估。
5. SEC 监管文件优先级高于 Nasdaq 媒体聚合；媒体可以提示事件，但不能覆盖监管文件中的修正或风险说明。
6. 不得使用分析师目标价生成走势概率、收益承诺或买卖指令。
7. 输出必须保留报告期、申报日期、市场时间、来源和仍缺失的行业供需上下文。
