---
name: watchlist-stock-research
description: 用自选股后台证据支持当前模型即时回答。
version: 1.1.0
---

# Watchlist Stock Research Runtime

- 仅在 `research_evidence_contract.path=watchlist_preanalysis` 时使用。
- 当前报价、价格和最新公司资讯以本轮刷新证据为准；后台报告只是证据底稿，禁止回放正文。
- 只有 `module_statuses` 明确标为复用的慢变模块才可复用，并保留报告期或生成时间；用户判断仍是用户假设，不是公司事实。
- 回答必须由当前 Hermes/DeepSeek Run 针对问题重新生成，先直接回答，再补与结论真正相关的边界。
- 不向用户显示内部状态码、供应商错误或后台任务名，也不因存在旧报告而跳过当前事实核验。
