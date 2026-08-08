---
name: financial-drivers
description: 基于同类报告期详细三表，拆解利润、费用率、营运资金与现金流变化，严格区分机械影响、可疑线索和未确认因果。
version: 0.1.0
metadata:
  hermes:
    tags: [finance, statements, profit, cashflow, attribution]
---

# Financial Drivers

## 目标

回答“利润为什么下降、毛利率为什么变化、现金流为什么转弱”等问题时，先用确定性三表科目定位变化落在哪里，再明确说明哪些只是复核线索，不能把报表相关性冒充业务因果。

## 输入

- `latest_period`、`comparable_period`：上一年度同类报告期；
- `profit_bridge`：毛利、营业利润和归母净利润变化及尚未桥接的差额；
- `expense_analysis`：费用金额、费用率和利润方向的机械影响；
- `working_capital_analysis`：应收、存货、应付相对收入的变化；
- `cashflow_analysis`：经营、投资、融资现金流，销售收现和资本开支代理；
- `confirmed_mechanical_drivers`：由报表恒等式或科目差额确定的机械影响；
- `plausible_clues`：只能用于下一步复核的线索；
- `unresolved_causes`：当前数据无法确认的业务原因。
- `company_explanations`：与当前报告期一致的财报全文原因摘录；属于公司明确解释，不是独立验证结论。

## 必须遵守

1. 只比较上一年度同类报告期；累计中报、三季报不得与一季报写成环比。
2. 先回答归母净利润实际变化，再说明毛利桥、费用率、税费、扣非差额和现金流分别贡献了什么。
3. `confirmed_mechanical_driver` 只表示数学或会计科目机械影响，不得写成已经证明的价格、产品结构、竞争、成本或客户原因。
4. `plausible_clue` 必须使用“可能、需要复核、线索”等表述；应收或存货增长快于收入不能直接写成经营恶化或财务造假。
5. `unexplained_operating_profit_change` 是未被已列科目桥接的差额，不得自行命名为减值、研发、补贴或公允价值变化。
6. 归母净利润与扣非净利润的差额只能提示核对非经常性损益明细，不能直接判断其可持续性。
7. 销售收现率、经营现金流/净利润和资本开支代理只描述本期披露口径；季度季节性必须保留。
   销售收现率上升不能自动解释为回款节奏改善、客户回款变好或应收风险下降；没有公司原文时，
   只能列出比率变化，并把收入确认、预收、结算时点等保留为尚待核验的可能影响。
8. 所有金额和百分点必须来自证据包，不在模型中重新计算或补写新数字。
   毛利率变化使用 `profit_bridge.gross_margin_change_pp`，销售收现率变化使用
   `cashflow_analysis.cash_received_from_sales_ratio_change_pp`；即使两端比例都已给出，也不得自行相减。
9. 不输出 BUY/HOLD/SELL、目标价、利润预测、涨跌概率或交易指令。
10. 若 `company_explanations` 非空，先写“公司在报告中解释为”，再说明它能解释哪个机械科目；不得把它改写成独立证实的唯一原因。
11. 结尾给出 1—3 个公告附注、后续报告或分业务披露的具体复核点，并重申公司解释仍需交叉验证。
