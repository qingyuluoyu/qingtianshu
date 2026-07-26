# A股任意股票五维研究 Skills v7.0.0

本版本修复了 v6.0.0 以制造业/东山精密类公司为隐含模板的问题。

五个 Skill 均为独立、可单独调用的通用 A 股研究代理。每个 Skill 内置：

- 公司会计与经营模型路由；
- 生命周期和特殊情形识别；
- 数据完整度与降级规则；
- 与公司类型匹配的指标和研究方法；
- 灵活叙事式报告结构；
- `dimension_report.json` 输出和图表规格；
- 任意 A 股适配失败案例。

标准链路：

Tushare + 爬虫 → research_packet.json → 单维度 Skill → dimension_report.json → HTML / PDF / DOCX。
