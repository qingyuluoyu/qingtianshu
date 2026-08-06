---
name: evidence-debate
description: 复用TradingAgents的牛方、熊方和风险委员会思想，但只允许围绕证据包中的可追溯事实展开分歧。
version: 0.1.0
metadata:
  hermes:
    tags: [bull, bear, risk, debate, tradingagents]
---

# Evidence Debate

## 目标

让用户看到支持、反方和风险证据，而不是只收到一个黑盒结论。

## 输入

`evidence_debate` 已由确定性服务生成：

- `bull_case`：支持继续研究的价格或情绪证据；
- `bear_case`：反方价格或信息证据；
- `risk_committee`：回撤、波动和覆盖缺口；
- 历史走查若不支持当前价格方向，必须进入 `risk_committee`，不能被牛方或熊方隐藏；
- `manager_view`：证据管理结论，不是交易指令。

## 必须遵守

1. 每个观点必须保留证据值和来源，不得让角色自由编造论据。
2. 牛方不能隐藏回撤、波动或缺失数据；熊方不能把风险描述成必然下跌。
3. 社区情绪只能作为弱证据，并明确其来源和置信度。
4. `manager_view` 只能表达“继续研究、风险优先、证据分化”等研究状态，不得改写为 BUY/HOLD/SELL。
5. 当牛熊证据同时存在时，直接展示冲突，不强行消除分歧。
6. 用户原假设属于待验证命题，不属于牛方事实。
7. 样本外历史方向一致率只是价格规则的诊断证据，不是未来概率或交易胜率。
