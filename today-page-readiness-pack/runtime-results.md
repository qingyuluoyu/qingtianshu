# 运行结果汇总

> 采集时间：2026-08-04 ｜ 测试数据库：qingshu_auth_test ｜ 测试用户：raudaudit999

---

## 接口响应总览

| 接口 | 方法 | 状态码 | 耗时 | 需认证 | 备注 |
|---|---|---|---|---|---|
| /session | GET | 200 | 0.02s | 是 | 返回用户会话信息 |
| /v1/today/overview | GET | 200 | 3.39s | 是 | 聚合 7 个子调用 |
| /indices?scope=all&group=china | GET | 200 | 0.82s | 否 | 6 个中国指数 |
| /markets/breadth | GET | 200 | 0.01s | 否 | 缓存命中 |
| /sectors/hot?limit=10 | GET | 200 | 0.51s | 否 | 10 个行业 |
| /system/data-health | GET | 200 | 0.01s | 否 | 67 项检查 |
| /me/watchlist/brief | GET | 200 | 0.20s | 是 | 新用户空列表 |
| /me/research-actions | GET | 200 | 0.03s | 是 | 新用户空列表 |
| /me/research-changes | GET | 200 | 0.01s | 是 | 新用户空列表 |

## 边界状态

### 401 无 Cookie
- /session: `{"code":"session_expired","message":"会话已失效或不存在"}`
- /v1/today/overview: 401（FastAPI 默认 detail）
- /me/watchlist/brief: 401
- /me/research-actions: 401
- /me/research-changes: 401

### 422 无效参数
- /indices?scope=invalid: `{"detail":[{"type":"literal_error","msg":"Input should be 'core' or 'all'"}]}`
- /sectors/hot?limit=200: 422（超过 le=100）

### 新用户空数据
- watchlist-brief: items=[], coverage={requested:0, available:0}
- research-actions: items=[], summary 全 0
- research-changes: items=[], events=[]

### data_health 状态
- status: "degraded"
- summary: {total:67, healthy:0, attention:19, critical:48}
- 无 healthy 项（测试环境无分钟线数据）

### SSE /events
- 状态码: 200
- Content-Type: text/event-stream; charset=utf-8
- 连接保持开放，初始发送 `{"type":"connected","time":"..."}`
- 心跳间隔 15 秒（`: heartbeat`）
