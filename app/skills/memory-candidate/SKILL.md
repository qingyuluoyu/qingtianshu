---
name: memory-candidate
description: 向用户确认系统只创建了待确认的记忆候选，未经确认不得声称已经形成长期记忆。
version: 0.1.0
metadata:
  hermes:
    tags: [memory, confirmation, user-workspace]
---

# Memory Candidate

## 目标

让用户清楚知道系统从对话中识别了什么，以及该内容当前是否已经进入长期记忆。

## 不可越过的状态规则

1. `status=candidate` 只表示“记忆候选”，绝不表示已保存为长期偏好。
2. 必须逐字表达“尚未确认”或同义的明确否定。
3. 不得说“已记住”“已生效”“以后会默认使用”或“会长期保留”。
4. 只有 API 完成 confirm、证据状态变成 `confirmed` 后，后续 Agent 才能把它当作用户记忆。
5. 不扩写、不推断用户没有说过的风险偏好或投资风格。

## 输出

用两句话：第一句复述候选内容；第二句说明尚未确认，并提示用户确认后才用于后续分析。
