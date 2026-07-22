---
name: earnings-quality
description: 比较同类财务报告期的增长、利润率、现金流与杠杆，识别盈利兑现的支持证据和矛盾。
version: 0.1.0
metadata:
  hermes:
    tags: [finance, earnings, cashflow, fundamentals, quality]
---

# Earnings Quality

## 目标

基于确定性结构化财务期回答“财报怎么看、利润为什么变化、现金流质量如何”，明确哪些事实已经披露、哪些原因仍需查阅公告原文。

## 输入

- `latest_report`：最新报告期；
- `comparable_report`：上一年度同类报告期；
- `factors`：营收、净利润、毛利率、净利率、现金流覆盖和杠杆变化；
- `supports`：相互支持的财务证据；
- `contradictions`：增长、利润率和现金兑现之间的矛盾；
- `review_points`：下一步应核对的科目和公告原文；
- `related_information`：用于定位可能解释的公告、监管文件或新闻标题。

## 必须遵守

1. 只比较上一年度同类报告期，不把一季报、中报、三季报或年度累计值互相当作环比。
2. 用户问“为什么”时，先回答已经确认的财务矛盾，再说明精确原因尚需核对费用、减值、非经常性损益、应收、存货和公告原文。
3. `related_information` 只能用于定位原文；标题不能单独证明利润或现金流变化的原因。
4. 经营现金流/归母净利润低于 1 只表示现金兑现需要复核，不得直接推断造假、经营恶化或未来下跌。
5. 毛利率、净利率和资产负债率变化必须使用“百分点”，不能误写成同比百分比。
6. 毛利率因子中的 `current_revenue_per_margin_point` 和 `current_revenue_margin_change_sensitivity` 是按本期营收做的静态敏感性测算；可以用于说明量级，但必须明确它不是实际毛利变动或利润下降原因的归因。
7. 明确展示支持证据与矛盾证据，不为了形成单一结论而隐藏其中一侧。
8. 不输出 BUY/HOLD/SELL、目标价、未来利润预测、涨跌概率或交易指令。
9. 结尾保留报告期、证据边界和 1—3 个可执行复核点。
