---
name: a-share-filing-evidence
description: 使用A股财报全文中公司明确披露的原因说明，并与结构化三表机械拆解严格分层。
version: 0.1.0
metadata:
  hermes:
    tags: [a-share, filing, full-text, causality, evidence]
---

# A-share Filing Evidence

## 目标

把财报全文中的公司解释用于回答“为什么”，但不把管理层解释冒充独立验证的唯一因果。

## 输入

- `filing_evidence.document`：报告标题、报告期和公告日期；
- `company_explanations` / `explicit_company_explanations`：正文中带有“主要因、由于、导致、原因分析”等明确归因语言的原文摘录；
- `reported_facts`：正文事实，但没有明确原因说明；
- `unresolved_themes`：报告原文尚未给出明确解释的主题。

## 必须遵守

1. `explicit_company_explanation` 必须写成“公司在报告中解释为”或“公司披露的原因是”，不得写成已被独立证明。
2. `reported_fact` 只能作为事实，不得自行补出价格、产品结构、竞争、成本、客户或季节性原因。
3. 报告期必须与结构化财务拆解的 `latest_period.report_date` 一致；不引用另一报告期解释当前变化。
4. 优先回答与用户问题直接对应的主题，例如财务费用对应汇兑与利息，减值对应应收或存货跌价。
5. 原文若只解释部分科目，要明确剩余利润桥或现金流原因仍未解决。
6. 所有数字和百分比必须原样来自证据包，不重新计算原文表格。
7. 不输出目标价、利润预测、涨跌概率、BUY/HOLD/SELL 或交易指令。
8. 结尾保留边界：公司原文是一手披露，但不是独立因果验证。
