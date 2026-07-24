# 清数智算 MVP 交接说明（2026-07-24）

## 1. 交接目的

本文件供下一位 Agent 直接接续“清数智算”主线开发。当前阶段已经完成李总策略近期无前视历史回放、空候选页面解释、历史信号后续走势与沪深300对照、即时 Agent 复盘入口，以及核心功能/数据/算法/Agent 架构 Word 报告。

下一位 Agent 不应重新设计已经完成的李总历史回放，也不要覆盖当前未提交的结构化 AI 写回与交易复盘改动。应先完成本阶段 Git 交付，然后回到正式 PRD 主线，优先改善整体产品效果。

## 2. 权威目录与 Git 状态

- 权威仓库：`/Users/chr/Documents/qingtianshu`
- 当前分支：`codex/structured-ai-writeback`
- 远端：`https://github.com/qingyuluoyu/qingtianshu.git`
- Git 上传指南：`/Users/chr/Documents/青树金融交易/GitHub仓库分支与文件上传使用说明.md`
- 产品任务清单：`/Users/chr/Documents/青树金融交易/qingshu-agent-demo/同事设计与当前实现对比及待完成清单_20260722.md`
- 七页高保真基准：`/Users/chr/Documents/青树金融交易/AI金融Agent产品方案/清数智算_七页高保真交互演示.html`

当前工作树包含本阶段未提交改动。禁止使用 `git reset --hard`、`git clean -fd`、强制推送或批量覆盖。提交前必须逐项审查并显式暂存。

## 3. 当前运行态快照

快照时间：2026-07-24 01:56（Asia/Shanghai）。运行数字会继续随后台 Worker 增长，后续引用时应重新读取，不要把本节数字当成永久常量。

- 服务地址：`http://127.0.0.1:8773/demo`
- 健康检查：`http://127.0.0.1:8773/health`
- 当前进程：PID `29188`
- 当前启动命令：`.venv/bin/python -m app --host 127.0.0.1 --port 8773 --no-browser`
- 数据库：`/Users/chr/.qingshu/qingshu.db`
- `/health`：`ok`
- Hermes：启用
- 默认文字模型：`deepseek / deepseek-v4-pro`
- 数据健康：`54/54 healthy`
- 通用后台任务：运行中
- 李总策略独立 Worker：运行中，默认每 30 秒推进

李总策略当前截面：

- A股名单：`5530/5530`
- 市值严格大于150亿元：`1216`
- 市值未达标：`4310`
- 缺少当日市值：`4`
- 可深度核验：`1169`
- 已深度处理：`1168`
- 剩余深度重试：`1`
- 明确未满足：`5471`
- 数据不完整：`59`
- 当前严格候选：`0`
- 当前触发：`0`
- 近期80交易日无前视回放：`234/1169`
- 已发布去重历史事件：`23`

当前规则漏斗：

`5530 → 1216 → 226 → 202 → 20 → 15 → 5 → 0`

最后5只股票均未通过“近10个交易日无跌幅达到或超过5%的阴线”。这说明当前空候选主要来自规则交集，而不是系统没有运行或完全缺少数据。

## 4. 标准安装与启动

### 4.1 推荐使用 uv

```bash
cd /Users/chr/Documents/qingtianshu
uv sync --frozen --extra dev
cp .env.example .env
uv run qingshu-start
```

服务器或不自动打开浏览器时：

```bash
uv run qingshu-start --host 0.0.0.0 --port 8773 --no-browser
```

### 4.2 标准 Python

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/qingshu-start --host 127.0.0.1 --port 8773
```

### 4.3 Docker

```bash
docker compose up --build -d
```

Docker 默认不启用 Hermes。需要模型能力时，应在部署环境安全配置 Provider 和密钥，不能把密钥写入仓库、README、测试输出或日志。

运行数据默认写入 `~/.qingshu`，不是仓库内固定绝对路径。README 已说明 uv、标准 Python、Docker 和服务器启动方式。

## 5. 本阶段完成的核心工作

### 5.1 李总策略近期无前视历史回放

新增：

- `app/services/li_zong_history.py`
- `tests/test_li_zong_history.py`

主要能力：

1. 默认回放每只股票最近80个可计算交易日。
2. 每个信号日只传入该日及以前的日线。
3. 使用信号日对应的历史 `daily_basic` 市值，禁止用当前市值回推历史。
4. 年度 ROE 和股东结构只接受公告日不晚于信号日的数据。
5. 连续候选或连续触发按阶段去重，避免同一段行情每天重复生成事件。
6. 保存信号后5/10/20个交易日的个股收益、沪深300收益、超额收益、最大上行、最大下行和累计路径。
7. 基准缺失或观察期不足时保持 `partial`，不猜补结果。
8. 回放结果保存到版本化 `tushare_dataset_snapshots`，数据集键为 `li_zong_history`。

边界：

- 当前是近期80交易日点时回放，不是多年全市场回测。
- 未计交易成本、涨跌停可成交性和实际成交价。
- 历史表现只用于复盘，不能直接推断未来收益。

### 5.2 空候选页面不再是空白

涉及：

- `app/main.py`
- `app/services/li_zong_strategy_service.py`
- `app/services/background.py`
- `app/static/demo.html`

已经实现：

1. 当前严格候选为0时，展示逐规则漏斗。
2. 展示历史真实候选/触发卡片，而不是演示数据或“接近候选”伪装。
3. 每张卡片展示信号日期、当时触发、信号后5/10/20日个股与沪深300表现。
4. 展示个股和沪深300累计路径双线。
5. 支持查看当时完整逐规则证据。
6. 支持“让 Agent 复盘”，把历史事件作为证据装入新一轮即时模型回答。
7. 页面历史区域可滚轮连续浏览。
8. 后台 Worker 即使仍有单只深度重试，也继续小批量推进历史覆盖，避免长期停滞。

接口：

- `GET /v1/stock-strategies/li-zong/history`
- `POST /v1/stock-strategies/li-zong/history/runs`（管理员/后台）

### 5.3 Agent 必须即时生成

李总历史卡片、预生成研究报告、历史对话和资料库内容只能进入本轮证据上下文，不能直接作为最终回复返回。

当前链路：

1. 识别市场/股票/行业/研究意图和多轮上下文。
2. `ResearchPlan` 选择实时模块、稳定证据、资料库和 Skills。
3. 确定性服务刷新行情、财务、事件、策略和历史证据。
4. Hermes 调用 `deepseek-v4-pro` 即时生成。
5. 数字与语义校验后原位完成最终稿。
6. 判断、任务、计划和复盘仅作为结构化候选；用户确认后才写入正式对象。

必须保留的产品要求：

- 不得把已保存报告或历史回答直接冒充本轮答案。
- 回答要区分事实、推断、反方证据、信息缺口和失效条件。
- 金融数字来自确定性数据或算法，不能让模型编造。
- 不自动交易，不生成目标价、仓位、未来概率或收益承诺。

### 5.4 结构化 AI 写回与交易复盘改动

以下改动属于本分支此前已经进行、必须保留的工作：

- `app/services/structured_ai.py`
- `app/services/trade_workflow.py`
- `tests/test_demo_action_plan_contract.py`
- `tests/test_trade_workflow_api.py`
- `RUIZHI_BRANCH_ABSORPTION_CHECKLIST_20260723.md`

本阶段已进一步接通结构化判断、任务、计划与复盘候选。下一位 Agent 在合并或重构时不能只保留李总历史文件而丢失这些改动。

## 6. 李总策略确定性规则

候选池要求以下9条全部通过：

1. 最近完整交易日总市值严格大于150亿元。
2. 最近连续5个已披露完整年度 ROE 每年均不低于10%。
3. 最新已披露十大股东/十大流通股东中，非自然人股东去重数量至少5名。
4. 最近约240个交易日至少6次收盘涨停。
5. 最近约240个交易日至少出现一次连续两日收盘涨停。
6. 最近10个完整交易日至少一次收盘涨停。
7. 最近10个完整交易日没有 `close < open` 且 `pct_chg <= -5%` 的阴线。
8. 最近20个交易日中至少有一天创最近360个交易日复权新高。
9. 连续3个交易日成交量均达到序列开始前20日均量的2倍。

候选通过后，以下三项任一通过则进入盘后人工复核触发池：

1. 当日收盘涨停。
2. 当日相对前收盘高开至少3.5%，且收阳。
3. 当日振幅严格大于9.8%，且收阳。

不要擅自放宽原始严格规则。下一阶段建议增加独立“接近满足观察池”，明确标注 `8/9`、`7/9` 等通过数量和失败原因，但不能把观察池股票称为李总策略候选。

## 7. 数据与算法支撑

### 7.1 数据来源

- 全球指数与黄金：腾讯、东方财富、Yahoo、新浪 XAU。
- A股全市场：Tushare兼容服务，覆盖名单、市值、日线、复权、真实涨跌停价。
- A股财务：Tushare 为主，东方财富 F10 补结构化年度 ROE 和三表证据。
- 股东与分析师预期：Tushare、东方财富。
- 公告、新闻和情绪线索：正式披露聚合、东方财富、新浪、股吧。
- 美股：SEC EDGAR、Nasdaq、腾讯等。
- 用户研究：SQLite 版本化快照、用户股票空间、判断、任务、操作和复盘。

### 7.2 已实现算法

- 收益率、MA20/60、RSI14、MACD、ATR14、布林带、量比、波动率和回撤。
- A股涨跌家数、成交额、涨跌分布分位和行业成分广度。
- 财报质量、利润与经营现金流驱动、三表勾稽。
- 同行业/同行同报告期、同口径比较。
- ResearchPlan 按问题选择行情、财务、股东、主营、预期、事件和估值模块。
- 李总策略确定性规则、点时历史回放和结果路径。
- 结构化判断、任务、计划与复盘候选写回。

### 7.3 当前数据边界

当前公开数据可以支撑 MVP，但不能保证：

- 交易所级逐笔、Level-2、集合竞价和完整盘口。
- 零延迟、生产级授权的全球行情。
- 完整授权新闻、研报全文和券商专有数据。
- 全历史机构持仓与长期行业样本变更。
- 商业 SLA、数据许可台账和多源自动故障切换。

商业化必须采购授权数据并建立许可、监控、灾备和数据质量体系。

## 8. 核心功能与架构 Word 报告

最终文件：

`/Users/chr/Documents/qingtianshu/清数智算MVP核心功能数据算法与Agent架构报告-20260724.docx`

构建脚本：

- `scripts/build_core_architecture_report_20260724.py`
- `scripts/build_core_architecture_visual_report_20260724.py`

报告共10页，包含：

1. 执行摘要。
2. 核心产品功能。
3. 李总策略真实漏斗。
4. 历史信号与沪深300后续走势。
5. 金融数据来源和边界。
6. 确定性算法。
7. Hermes/DeepSeek 即时生成链路。
8. 系统架构。
9. 安装、验证和下一阶段。

报告使用高分辨率中文页面图片嵌入 DOCX，原因是隔离 LibreOffice 环境无法稳定渲染 DOCX 原生中文字体。最终 DOCX 已用标准文档渲染工具生成10页 PNG 和 PDF，并逐页检查：中文完整、无溢出、无重叠、截图清晰、底部与页脚无冲突。

报告运行数字从数据库动态读取。最后一次报告冻结快照为历史回放 `229/1169`、23个事件；后台随后已经增长，不能要求报告数字与实时数据库永久一致。

内部 QA 目录：

`/tmp/qingshu_visual_report_render_final_v3`

该目录属于临时证据，不是正式交付物。

## 9. 自动化与浏览器验收

本阶段最近一次完整自动化记录：

- `558 passed`
- `ruff check app tests scripts` 通过
- Python 编译通过
- 内联 JavaScript `node --check` 通过
- `uv lock --check` 通过
- `git diff --check` 通过
- `tests/test_portability.py` 通过

本次又单独运行李总策略、服务与历史回放测试，全部通过。

提交前仍必须重新执行完整命令，以覆盖最后的文档和脚本改动：

```bash
cd /Users/chr/Documents/qingtianshu
.venv/bin/pytest -q
.venv/bin/ruff check app tests scripts
.venv/bin/python -m compileall -q app tests scripts
git diff --check
uv lock --check
.venv/bin/pytest -q tests/test_portability.py
```

内联 JavaScript 检查应沿用 `VERIFICATION.md` 中现有提取方式，不能只检查独立 `.js` 文件，因为当前主要前端脚本仍内嵌在 `app/static/demo.html`。

真实浏览器已检查：

- 个股研究空间整体页面正常。
- 李总策略漏斗正常。
- 历史信号卡片正常。
- 个股与沪深300曲线正常。
- 页面滚轮浏览正常。
- 截图已进入最终 Word 报告。

仍需补做：

- “查看当时证据”按钮级完整 E2E。
- “让 Agent 复盘”按钮级完整 E2E，包括模型即时生成、引用和失败恢复。
- 接近满足观察池的页面和 Agent 问答。
- 多会话历史、诊大盘、诊个股、选股、个股空间之间的完整 R1 E2E。

## 10. 当前未完成主线与优先顺序

### P0-1 接近满足观察池

目标：严格候选为空时仍提供有用研究对象，但不篡改策略。

建议实现：

- `9/9`：严格候选。
- `8/9`：接近满足，突出唯一失败规则。
- `6-7/9`：研究观察，列出缺口和失败项。
- `data_incomplete`：单独分区，不能与规则失败混排。
- 支持按通过数量、失败规则和最新信号排序。
- Agent 必须明确这些股票不是当前严格候选。

### P0-2 统一整体前端

以七页高保真 Demo 和正式 PRD 为准：

- 收敛导航、字号、颜色、卡片密度和信息层级。
- 今日观察不占据不合理的首页主导位置。
- AI研究采用 DeepSeek 式多会话布局，支持历史对话。
- 诊大盘、诊个股使用同一 Agent，但右侧为更干净的专用研究页面并自动联动 K 线。
- 用户不可见后台任务名、数据源失败、内部枚举和调试信息。

### P0-3 选股与个股研究闭环

- 继续按《个股功能增强_主Agent实施说明.md》和 Tushare 说明推进。
- 打通选股结果 → 保存线索 → 股票长期空间 → 即时 Agent → 判断/任务 → 后续变化 → 复盘。
- 强化财报质量、现金流驱动、行业同行、估值、反证和下一证据。
- 自选股中兴通讯、中际旭创、英伟达继续保持服务器预生成报告，但报告只作为即时对话证据。

### P0-4 用户订阅与今日观察联动

- 李总策略订阅、通知偏好、触发去重和人工复核任务。
- 严格候选或触发进入今日观察。
- 不自动写入持仓、不自动生成交易动作。

### P0-5 Agent 可用性

- 降低等待时间。
- 某个证据模块失败时独立重试或降级，不让整轮研究直接失败。
- 保证 Enter 发送、多会话保存、流式原位更新和最终回答不跳成另一段固定文案。
- 继续用真实问题测试回答差异，不能依赖固定市场模板。

### P1 生产底座

- PostgreSQL/正式数据库集群。
- 独立任务队列和 Worker。
- 认证、权限、限流、监控、灾备和多实例一致性。
- 数据授权和商业 SLA。
- 完整交易成本、可成交性与长期样本评估。

## 11. 下一位 Agent 的建议起手顺序

1. 完整阅读本文件、`README.md`、`VERIFICATION.md` 和任务清单第17节。
2. 查看 `git status` 和 `git diff`，确认没有覆盖已有结构化 AI 改动。
3. 重新读取 `/health` 和数据库，不复用本文件中的旧动态数字。
4. 运行完整测试和静态检查。
5. 更新任务清单中的实时快照和验证结果。
6. 显式暂存本阶段文件，执行 `git diff --cached --check`。
7. 提交并推送 `codex/structured-ai-writeback`。
8. 推送成功后优先实现“接近满足观察池”，随后做统一前端和选股/个股研究闭环。

建议提交命令：

```bash
git add README.md VERIFICATION.md HANDOVER_QINGSHU_20260724.md \
  RUIZHI_BRANCH_ABSORPTION_CHECKLIST_20260723.md \
  app/db.py app/main.py app/services/agent.py app/services/background.py \
  app/services/li_zong_strategy_service.py app/services/li_zong_history.py \
  app/services/structured_ai.py app/services/trade_workflow.py app/static/demo.html \
  tests/test_demo_action_plan_contract.py tests/test_li_zong_history.py \
  tests/test_li_zong_strategy_service.py tests/test_trade_workflow_api.py \
  scripts/build_core_architecture_report_20260724.py \
  scripts/build_core_architecture_visual_report_20260724.py \
  '清数智算MVP核心功能数据算法与Agent架构报告-20260724.docx'

git diff --cached --check
git status --short
git commit -m "feat: add point-in-time Li Zong history and architecture report"
git push -u origin codex/structured-ai-writeback
```

提交前应根据真实 `git diff` 调整显式文件列表，不能机械复制后遗漏或误加文件。

## 12. 必须遵守的边界

- 不把模型回答存档直接当成当前回答。
- 不让 LLM 编造金融事实、阈值、目标价或收益概率。
- 不用未来财务、未来股东或当前市值回推历史信号。
- 不把数据不完整误写成规则失败，也不把规则失败包装成候选。
- 不自动交易、不自动下单、不自动生成仓位。
- 不在前端展示内部错误、供应商异常和后台任务名称。
- 不写入或输出用户 Token、Hermes 密钥和数据库隐私数据。
- 不为局部守卫或低收益细节长期偏离正式 PRD 主线。
- 任何阶段性完成都必须更新 README、验证记录、任务清单和 Handover，并推送 GitHub。
