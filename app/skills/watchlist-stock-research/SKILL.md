---
name: watchlist-stock-research
description: 使用自选股后台预分析证据支持本轮即时问答，严格区分最新刷新、慢变复用、用户假设和证据缺口。
version: 1.0.0
metadata:
  hermes:
    tags: [finance, stock, watchlist, evidence, research]
---

# Watchlist Stock Research

## 适用范围

仅当 `research_evidence_contract.path=watchlist_preanalysis` 时使用。该股票已经属于当前
用户的自选研究范围，后台可能已经准备研究证据。

## 证据装配规则

1. 价格、当前报价、公司资讯和最新估值仍按本轮问题刷新；不得因为存在服务器报告而跳过当前事实。
2. 财报质量、主营结构、股东结构、同行和历史走查等慢变模块，可以按研究计划规定的最大时效复用。
3. 只有 `module_statuses` 标为 `reused` 或 `reused_fallback` 的模块才能称为复用证据；不得把整份报告都说成最新。
4. `precomputed_report_reference` 只说明证据底稿的版本和时间，不得引用或复述服务器报告正文。
5. `user_thesis` 和股票空间中的正式判断属于用户假设或用户确认内容，不是公司事实。

## 回答规则

- 本轮回答必须由当前 Hermes/DeepSeek Run 重新生成，并直接回答用户问题。
- 先使用最新刷新证据；慢变复用内容必须保留财务报告期或证据生成时间。
- 如果关键模块只取得 `reused_fallback`，自然说明“最新来源暂未更新，本轮使用最近可核验证据”，
  不展示内部状态码、供应商错误或后台任务名。
- 只把与当前问题相关的缺口放在结尾，不能用缺口抹掉已经可回答的事实。
- 正式披露和媒体报道同时存在时分别陈述，不把混合材料统称为媒体线索；直接列实际要点，
  不预告固定证据数量。
