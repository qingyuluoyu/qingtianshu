---
name: online-stock-research
description: 为非自选股票按本轮问题在线取得所需证据。
version: 1.1.0
---

# Online Stock Research Runtime

- 仅在 `research_evidence_contract.path=online_research` 时使用，不得把服务器预生成报告当成本轮证据。
- 当前报价、最近完整日线、公司资讯和事件按研究计划实际刷新；只取 `selected_modules`，不为简单问题加载全景报告。
- 行情与财报保留各自时间，正式披露、媒体线索和社区讨论保持可信层级；取到新闻不等于证明股价因果。
- 当前来源没有更新时只使用带原始时间的最近可核验证据，并降低结论强度；不得补造缺失数字或原因。
- 回答由当前 Hermes/DeepSeek Run 针对本题即时生成，第一段直接解决问题，不展示检索过程、内部状态码或供应商错误。
