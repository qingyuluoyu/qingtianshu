# 六个正式页面真实运行与基础验收：实施计划

> **执行约束：** 本计划在 `codex/formal-six-page-ui-v1` 的独立 worktree 内执行；所有真实浏览器验收都使用隔离 Docker PostgreSQL、FastAPI 生产镜像和镜像内 `/app/frontend/dist`，不启动 Vite、不使用 Playwright 路由 mock 或 `route.fulfill`。外部行情与模型凭据缺失时，只验收明确的不可用/空态，不伪造金融数据。

**目标：** 为今日观察、透明选股、我的关注、个股研究、金融顾问、研究中心建立一条可重复的“注册登录 → 真实 API → 页面展示/交互 → 刷新恢复 → 用户隔离”生产验收链，并只修复验收实际发现的阻塞问题。

**架构：** 保持单个 FastAPI 服务托管 React SPA 与同源 API/SSE。扩展现有 `frontend/scripts/run_docker_production_e2e.py`，使其每次创建临时镜像、临时 PostgreSQL 容器、临时网络和临时注册用户。生产 Playwright 套件只访问该临时运行环境；已有 `frontend/e2e/` mock 套件继续保留为组件展示回归，不作为正式接口证明。

**技术栈：** React + TypeScript + TanStack Query + Playwright；FastAPI + PostgreSQL；Docker 多阶段构建。

---

## 工作包 1：冻结真实验收运行器与运行身份

**文件：**
- 修改：`frontend/scripts/run_docker_production_e2e.py`
- 修改：`frontend/playwright.production.config.ts`
- 修改：`frontend/e2e-production/production.spec.ts`
- 新增：`frontend/e2e-production/helpers.ts`
- 测试：`frontend/e2e-production/production.spec.ts`

**步骤：**

1. 先为生产测试补充一个会失败的最小断言：`overview.summary.market_date` 可以是 `string | null`，且 UI 必须用生成时间或“数据日期待确认”降级展示；不得把合法的 `null` 误判为生产链路失败。
2. 将 Docker 运行器向 Playwright 显式传递运行身份（镜像标签、临时容器名、基地址、环境模式），但不传递数据库密码、Cookie 或模型密钥给测试报告。
3. 在 helper 中集中创建两个临时正式账号、监听 console/page error、收集 API/SSE/resource 响应；禁止每个页面重新写一套监听逻辑。
4. 保留现有 Today、认证、旧会话吊销、SSE、legacy 与 API/SPA 路由分流断言；把其断言改为编码无关且与当前 JSON 合同一致。

**验收：**

```powershell
cd frontend
npm run test:e2e:docker
```

期望：临时容器完成清理；测试只由生产 React dist 驱动；`/ready`、`/today`、`/legacy`、API 与 SSE 的协议断言均实际通过。

---

## 工作包 2：把六页的真实读取与空态纳入 Docker Playwright

**文件：**
- 新增：`frontend/e2e-production/six-pages.spec.ts`
- 必要时修改：`frontend/e2e-production/helpers.ts`
- 必要时修改：对应页面的测试 ID 或可访问名称（`frontend/src/features/*/*.tsx`）
- 测试：`frontend/e2e-production/six-pages.spec.ts`

**步骤：**

1. 注册后在同一浏览器上下文依次访问 `/today`、`/screening`、`/watchlist`、`/stocks/000063.SZ`、`/advisor`、`/research-center`，确认均由 React HTML 托管、主标题/主区域可见、无未处理 page error、无资源 404。
2. 对每页记录真实业务请求、状态码与 JSON content type；只允许后端合同明确的空态和外部 Provider 错误。不得以页面 mock 或前端 `0` 值替代失败响应。
3. 今日观察：确认五个核心指数排序、市场宽度、行业与个人研究模块分别完成或给出模块级状态；history 或 Provider 不可用不能阻塞指数基础卡。
4. 透明选股：调用真实 `/stock-screener/profiles` 与 `/me/stock-screener`、李总候选/最近运行/回测端点。没有已发布快照时，页面必须显示后端 `snapshot_not_ready` 的可理解状态，而不是无限加载、扫描或假候选。
5. 我的关注：先断言真实空态，再经真实 `POST /me/watchlist` 创建一条用户关注，刷新页面验证 workspace/关系展示，再经真实删除接口验证列表回到空态。
6. 个股研究：访问深层 `/stocks/000063.SZ`，验证 `/v1/stocks/{symbol}/page`、history、workspace、theses、observation tasks、position、deep session 的独立加载；没有用户 workspace/thesis/position 时必须是明确空态。另用 request context 验证 `/stocks/{symbol}/history` 永远返回 JSON/JSON 错误，不被 SPA 捕获。
7. 金融顾问：验证会话列表与空态，创建会话后重载页面。Hermes 未配置时，提交消息须显示确定性的不可用错误，不能伪造建议；在显式配置模型的独立环境中才追加一次真实对话和 SSE 生命周期断言。
8. 研究中心：验证 changes、outcomes、actions、trade reviews、writebacks 的真实空态/可用态；对于不存在的报告，显示模块级空态而不是让整页失败。

**验收：**

```powershell
cd frontend
npm run test:e2e:docker
```

期望：六条正式路由均从生产镜像加载；没有 `page.route`、`route.fulfill` 或假财经数据参与。

---

## 工作包 3：验证写操作、409 与跨用户资源边界

**文件：**
- 修改：`frontend/e2e-production/six-pages.spec.ts`
- 必要时修改：`frontend/e2e-production/helpers.ts`
- 必要时修改：只与失败行为直接相关的前端功能文件
- 测试：`tests/test_registered_user_isolation.py`、`tests/test_observation_tasks.py`、`tests/test_stock_domain.py`、`tests/test_agent_stream.py`

**步骤：**

1. 为用户 A 通过正式 API 创建关注 workspace、thesis candidate、observation task 与 conversation；记录真实返回 ID 和版本号。
2. 使用独立 Cookie 的用户 B 对 A 的精确 ID 执行读取、修改、确认、拒绝和 chat stream 请求，逐个断言 `404`（或合同定义的拒绝状态）；B 的列表也不得出现 A 的内容。
3. 对 A 的 thesis/writeback 或 trade-review 写操作执行一次正常版本变更，再用过期 `base_version` 重新提交，确认服务端返回 `409` 且前端显示“刷新后重试”而不静默覆盖。
4. 如果页面尚无对应用户触发入口，测试允许用同源正式 API 构造前置资源，但页面侧必须验证真实读取、空态和可见的状态/错误表现；不通过数据库直写造页面数据。
5. 若发现跨用户泄露、写入越权、版本冲突被吞掉、401 导致重复认证弹窗或任一核心操作无限等待，先新增针对性失败测试，再做最小修复。

**验收：**

```powershell
python -m compileall -q app
pytest -q tests/test_registered_user_isolation.py tests/test_observation_tasks.py tests/test_stock_domain.py tests/test_agent_stream.py
cd frontend
npm run test:e2e:docker
```

期望：所有资源均以用户 A 的实际 ID 被用户 B 交叉访问；没有仅比较列表长度的假隔离断言。

---

## 工作包 4：按真实失败最小修复六页可用性

**文件：**
- 仅修改 Docker E2E 已证实失败模块的前端组件、adapter、query 或 FastAPI 路由/服务
- 对应新增或修改单元、组件、API 集成测试

**步骤：**

1. 每个问题先记录：请求 URL、状态码/响应、用户状态、可复现页面路径和影响范围；区分前端合同解析错误、后端合同缺失、Provider 不可用和部署路由错误。
2. 按测试驱动方式先写失败测试，再实施最小修复；不得为了通过验收新增 Dashboard、假市场数据、静态示例关注或绕开认证。
3. 优先修复会使整个页面崩溃、请求无限重试、合法 `null` 被误处理、外部 Provider 失败扩散、深层刷新被 SPA/API 分流错误吞掉、390px 文档横向溢出的缺陷。
4. 保持认证合同、数据库 schema、SSE 协议和 `app/static` legacy 内容不变；若必须修改其中任一项，停止并单独说明兼容与迁移方案。

**验收：**

```powershell
cd frontend
npm test
npm run build
cd ..
python -m compileall -q app
pytest -q <受影响的后端测试>
cd frontend
npm run test:e2e:docker
```

期望：修复仅覆盖已复现缺陷，所有改动有单测/真实生产 E2E 证据。

---

## 工作包 5：真实浏览器视觉与发布前证据

**文件：**
- 修改：`frontend/e2e-production/six-pages.spec.ts`
- 修改：`frontend/scripts/run_docker_production_e2e.py`
- 新增（仓库外）：`F:/tools/qingshu-six-page-acceptance-evidence/<commit>/`
- 必要时新增：`docs/superpowers/reports/2026-08-07-six-page-real-acceptance.md`

**步骤：**

1. 在 Docker 生产环境以 Chromium 采集六页 1440×900 截图，并至少采集 Today、Screening、Watchlist、Stock Research 的 390×844 截图与全页文档宽度。
2. 汇总每页 console error、page error、资源 404、API 404/5xx、SSE 连接数、Provider 状态和数据新鲜度标识；报告由测试自动写到仓库外，绝不提交 screenshot、video、cookie、密码或数据库连接串。
3. 运行完整前端单测、前端构建、受影响后端测试、Docker 生产 E2E、镜像运行时无 Node/npm 断言与 compose 配置检查。
4. 只有六页在同一镜像/commit、同一隔离数据库、同一认证方式下完成真实访问，且双用户越权被拒绝，才能给出“基础验收通过”；外部数据/模型未配置的模块必须标为环境阻塞，不可写成已完成。

**验收：**

```powershell
cd frontend
npm test
npm run build
npm run test:e2e:docker
cd ..
python -m compileall -q app
docker compose --env-file staging.env.example config --quiet
```

期望：提供实际命令、提交、截图目录、通过/失败清单与手工复验步骤；没有把 mock 浏览器测试当作真实前后端验收。

---

## 依赖与执行顺序

1. 工作包 1 先建立可识别、可复现的生产验收环境。
2. 工作包 2 使用该环境证明六页读取与空态。
3. 工作包 3 在同一环境验证私有写入、409 与跨用户边界。
4. 工作包 4 只修正前述真实失败。
5. 工作包 5 在修复后的同一提交上产出发布证据。

## 明确不在本轮范围

- 新增金融指标、行情供应商、选股策略或首页聚合 Dashboard。
- 伪造数据、在浏览器 mock API、用数据库 SQL 直写制造页面内容。
- 修改认证合同、数据库 schema、SSE 协议、旧 `app/static` 内容。
- 反向代理、域名、TLS、Caddy 或云服务器部署编排。

