---
name: a-share-information
description: 分层使用A股公司公告、媒体新闻和社区讨论，形成可追溯的信息与情绪证据，禁止把低可信讨论当成公司事实。
version: 0.1.0
metadata:
  hermes:
    tags: [a-share, announcement, news, sentiment, evidence]
---

# A-share Information

## 数据层级

1. `announcements`：公司公告，最高优先级；引用标题后提示用户核对原文。
2. `news`：媒体事件线索；标题可能夸大，不能替代公告和财务数据。
3. `social_posts`：公开股吧样本；只反映部分零售讨论，最低可信度。
4. `sentiment`：公开关键词、互动权重和样本量计算的启发式摘要，不是模型自由判断。

## 必须遵守

- 新闻与公告矛盾时，以公告原文为准。
- 社区情绪必须同时给出 `sample_size`、`confidence`、`method` 和局限。
- 社区情绪的方向必须严格使用 `sentiment.band`；不得因为看到少数负面帖子，就把“偏多”或“轻微偏多”改写成“转负”、“偏空”或“悲观”。
- 不把阅读量、评论数或“看多”帖子解释成真实资金流。
- 不把媒体标题中的预测、目标价或评级当作清数智算自己的结论。
- 证据缺失时明确降低置信度，不补造新闻或社区观点；不对用户显示供应商或系统故障名称。
