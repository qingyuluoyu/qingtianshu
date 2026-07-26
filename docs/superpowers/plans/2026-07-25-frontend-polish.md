# 前端专业化打磨实施计划（第三轮）

- 日期：2026-07-25
- 设计：`docs/superpowers/specs/2026-07-25-frontend-polish-design.md`（用户已确认，含五个决策）
- 分支：`feat/frontend-polish`（基于 main 9182e95）
- 范围：仅 `app/static/high-fidelity-demo.html`、`app/static/high-fidelity-demo.js`、`app/static/high-fidelity-demo.css`

## 全局约束（每个任务必读）

1. **精确字符串替换**：每个步骤给出「旧串→新串」，旧串必须在文件中完整精确匹配（含全角空格、缩进）；不匹配则 STOP 并在报告中说明，禁止自行变通。
2. JS 保持 ES5 风格（`var`、逗号链）；HTML/CSS 保持现有排版风格（CSS 为 4 空格缩进的超长单行）。
3. **工作树有大量无关预存改动，严禁 `git add -A` / `git commit -a`**；每任务只 `git add` 本任务指定文件。例外：Task 4 的 CSS 提交**有意包含**该文件的 11+/8- 预存改动（用户自有视觉微调：logo img、watch-search-result-row、market-review、kline-zoom-controls、source-mark 等——前两轮已批准同模式夹带，溯源记录于提交信息）。
4. 实现者禁止启动服务器/浏览器；验证统一由控制器在 Task 5 执行。
5. 每任务完成后运行该任务的静态校验命令，然后提交并写报告 `.superpowers/sdd/task-N-report.md`（N=1..4，本轮为第三轮，覆盖写即可）。
6. 禁止改动本计划未列出的任何字符串、注释、标识符（`available`、`run` 等作为代码标识符/枚举比较保留原样，本轮只改用户可见文案）。

## Task 1: HTML 文案与结构

**Files:** Modify `app/static/high-fidelity-demo.html`

- [ ] **Step 1: head 与侧栏**

```html
旧:   <meta name="description" content="清数智算 AI 智能投研平台七页交互演示">
新:   <meta name="description" content="清数智算：面向 A 股个人投资者的个股研究与投资复盘工作台">

旧:   <title>清数智算｜AI 智能投研平台</title>
新:   <title>清数智算｜智能投研工作台</title>

旧: <div class="promo"><strong>AI赋能投研</strong><p>洞见价值　智赢未来</p>
新: <div class="promo"><strong>专注个股研究与投资复盘</strong><p>洞见价值　智赢未来</p>
```

- [ ] **Step 2: 顶栏 toast 与角标**

```html
旧: <button class="top-action" data-toast="暂无新消息"><span class="symbol">♧</span><span>消息</span><i class="badge">12</i></button>
新: <button class="top-action" data-toast="暂无新消息"><span class="symbol">♧</span><span>消息</span></button>

旧: data-toast="已打开收藏夹"
新: data-toast="收藏功能即将开放"

旧: data-toast="演示数据已导出"
新: data-toast="导出功能即将开放"

旧: data-toast="设置面板已打开"
新: data-toast="设置功能即将开放"
```

- [ ] **Step 3: 今日观察与评分库按钮/状态**

```html
旧: <button class="btn small" id="refreshTodayData" type="button">刷新数据</button>
新: <button class="btn small" id="refreshTodayData" type="button">更新行情</button>

旧: <p class="muted" id="stockDataStatus" style="margin:0 0 10px">正在加载真实个股数据…</p>
新: <p class="muted" id="stockDataStatus" style="margin:0 0 10px">正在加载个股数据…</p>

旧: <button class="btn small" id="refreshStockData" type="button">刷新个股数据</button>
新: <button class="btn small" id="refreshStockData" type="button">更新个股数据</button>

旧: <span class="kline-status" id="klineStatus">日K · 正在连接真实行情…</span>
新: <span class="kline-status" id="klineStatus">日K · 正在连接行情…</span>

旧: <button class="btn small">更多 ›</button>
新: <button class="btn small">查看全部</button>
```

- [ ] **Step 4: 评分库情报面板**

```html
旧: <h3>市场与研报 <small class="muted">· 关键词直达 + 行业AI精选</small></h3>
新: <h3>市场与研报 <small class="muted">· 外部检索 + 行业重点资讯</small></h3>

旧: <h4 id="stockNewsTitle">公告、市场与研报</h4><p>按当前股票关键词直达七大资讯平台</p></div><span class="pill">关键词直达 ↗</span>
新: <h4 id="stockNewsTitle">公告、市场与研报</h4><p>一键跳转七大资讯平台检索结果</p></div><span class="pill">查看相关内容 ↗</span>

旧: <h4 id="stockInsightTitle">行业AI精选 · 5条</h4><p>联网搜索后由大模型筛选，每三天更新一次</p></div><span class="pill blue" id="stockInsightStatus">三天一更</span>
新: <h4 id="stockInsightTitle">行业重点资讯 · 5条</h4><p>联网检索后由 AI 整理，每三日更新</p></div><span class="pill blue" id="stockInsightStatus">每三日更新</span>
```

- [ ] **Step 5: AI研究页**

```html
旧: <h3 style="margin-bottom:4px">详细回答 <small>（五维并行）</small></h3>
新: <h3 style="margin-bottom:4px">完整报告 <small>（五维并行）</small></h3>

旧: <b>可选增强</b>
新: <b>深度报告</b>

旧: id="startParallelAnalysis" type="button">生成详细回答</button>
新: id="startParallelAnalysis" type="button">生成完整报告</button>

旧: id="researchEvidenceMeta">证据快照未建立</span>
新: id="researchEvidenceMeta">暂无证据</span>

旧: <h3 style="margin:0">五维研究 <small>（结果随 run 保存）</small></h3>
新: <h3 style="margin:0">五维研究 <small>（结果自动保存）</small></h3>
```

- [ ] **Step 6: 我的关注**

```html
旧: <button class="btn primary" id="watchAddSubmit" type="submit" disabled>加入关注</button>
新: <button class="btn primary" id="watchAddSubmit" type="submit" disabled>添加关注</button>
```

- [ ] **Step 7: 个人复盘示例标注**

```html
旧: <h2 style="font-size:18px">本周复盘（06.23 - 06.29）</h2>
新: <h2 style="font-size:18px">本周复盘（06.23 - 06.29） <span class="pill orange">示例数据</span></h2>
```

- [ ] **Step 8: 个人中心静态内容替换（先做此步，再做 Step 9，保证旧串唯一）**

删除三行物理行并插入一行：
- 删除以 `      <div class="profile-top"><article class="card profile-card"><div class="identity">` 开头的整行（原 222 行，超长单行）
- 删除以 `      <div class="profile-main"><div class="stack">` 开头的整行（原 223 行，超长单行）
- 删除行 `      <p class="footer-note">演示数据，仅供参考</p>`（原 224 行，个人中心 section 内的那一行；今日观察 section 另有同文案行，Step 9 处理）
- 在 `      <h1>个人中心</h1>` 行之后插入一行：`      <p class="muted">正在加载个人数据…</p>`

完成后 `#page-profile` section 应恰好为：

```html
    <section class="page" id="page-profile">
      <h1>个人中心</h1>
      <p class="muted">正在加载个人数据…</p>
    </section>
```

- [ ] **Step 9: 今日观察页脚（Step 8 完成后该旧串全文件唯一）**

```html
旧: <p class="footer-note">演示数据，仅供参考</p>
新: <p class="footer-note">示例数据，仅供参考（示例环境，行情非实时）</p>
```

- [ ] **Step 10: 校验与提交**

```bash
grep -c "演示数据\|AI赋能投研\|关键词直达\|行业AI精选\|可选增强\|证据快照未建立\|随 run 保存\|加入关注\|七页交互演示\|badge\|profile-top\|profile-main" app/static/high-fidelity-demo.html   # 预期 0
grep -c "添加关注\|查看全部\|每三日更新\|示例数据" app/static/high-fidelity-demo.html   # 预期 ≥5
git add app/static/high-fidelity-demo.html
git commit -m "feat(copy): HTML 文案清理与个人中心静态演示内容移除"
```

## Task 2: JS 文案A（今日/评分/情报/K线）

**Files:** Modify `app/static/high-fidelity-demo.js`

- [ ] **Step 1: 今日观察状态行（js:734）**

```js
旧:       if(status)status.textContent=(snapshotDate?'每日固定快照 '+snapshotDate+' · ':'')+(errorCount?'部分模块后台补齐中':'数据已更新');
新:       if(status)status.textContent=(snapshotDate?'行情截至：'+snapshotDate:'行情数据已就绪')+(errorCount?' · 部分数据补齐中':'');
```

- [ ] **Step 2: 行情来源兜底（js:794、1108、1115）**

```js
旧: '　数据来源：'+(quote.source||'后端聚合接口')
新: '　数据来源：'+(quote.source||'多源行情')

旧: (cachedMeta.adjustment||'真实行情')+' · '+(cachedMeta.source||'后端聚合接口')
新: (cachedMeta.adjustment||'原始行情')+' · '+(cachedMeta.source||'多源行情')

旧: (meta.adjustment||'真实行情')+' · '+(meta.source||'后端聚合接口')
新: (meta.adjustment||'原始行情')+' · '+(meta.source||'多源行情')
```

- [ ] **Step 3: 数据状态枚举中文化（js:802，单行内替换）**

```js
旧: quoteState=dataStatus.quote||'unavailable',financialState=dataStatus.financials||'unavailable';status.innerHTML=escapeHTML(stockState.name+' · 行情 '+quoteState+' · 财务 '+financialState)
新: quoteState=dataStatus.quote||'unavailable',financialState=dataStatus.financials||'unavailable',stateText=function(s){return s==='available'?'正常':s==='warming'?'准备中':'暂无数据'};status.innerHTML=escapeHTML(stockState.name+' · 行情 '+stateText(quoteState)+' · 财务 '+stateText(financialState))
```

- [ ] **Step 4: 状态 pill 文案（js:879、893、913）**

```js
旧: status.textContent=available===5?'真实数据':'部分可用'
新: status.textContent=available===5?'数据完整':'部分维度缺失'

旧: status.textContent=data.status==='available'?'真实数据已更新':data.status==='warming'?'后台准备中':'部分数据可用'
新: status.textContent=data.status==='available'?'数据已就绪':data.status==='warming'?'数据准备中':'部分维度缺失'

旧: <div class="industry-factor-empty">没有使用模拟分数，请稍后刷新真实数据</div>
新: <div class="industry-factor-empty">暂无行业数据，请稍后重试</div>
```

- [ ] **Step 5: 行业精选（js:657、659、664）**

```js
旧:     if(status)status.textContent=payload&&payload.status==='completed'?'已更新 · 三天有效':payload&&payload.status==='not_configured'?'等待Tavily密钥':'三天一更';
新:     if(status)status.textContent=payload&&payload.status==='not_configured'?'本期未纳入该来源数据':'每三日更新';

旧: <span class="admin-badge">AI筛选</span>
新: <span class="admin-badge">AI整理</span>

旧: <div class="empty-state">正在联网读取行业信息并筛选…</div>
新: <div class="empty-state">正在联网检索行业信息并整理…</div>
```

- [ ] **Step 6: 校验与提交**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -c "真实数据\|后端聚合接口\|真实行情\|Tavily\|三天一更\|三天有效\|AI筛选\|后台准备中\|部分数据可用\|部分模块后台补齐中\|每日固定快照" app/static/high-fidelity-demo.js   # 预期 0
git add app/static/high-fidelity-demo.js
git commit -m "feat(copy): 评分库/今日观察状态文案去开发术语，数据状态中文化"
```

## Task 3: JS 文案B（研究/关注/复盘/个人中心）+ 死代码清理

**Files:** Modify `app/static/high-fidelity-demo.js`（在 Task 2 产物上继续）

- [ ] **Step 1: 关注（js:245、249）**

```js
旧:       toast('已加入关注');
新:       toast('已添加关注');

旧: <td colspan="9">正在读取关注股票…</td>
新: <td colspan="10">正在读取关注股票…</td>
```

- [ ] **Step 2: 删除会员购买死代码（js:250-267，共 18 行）**

完整删除以下区块（从 `var accountInfo` 到其闭合 `}`，含 `if(false&&accountInfo){` 全部内容）：

```js
  var accountInfo=$('.account-info');
  if(false&&accountInfo){
    var purchaseCard=accountInfo.closest('.card');
    ...（中间为会员购买/立即购买/订单创建逻辑，原样删除）...
  }
```

删除后原 249 行（watchRows）与 268 行注释 `/* ============ AI研究页：持久化 run + 同快照五维 + 一次综合写作 ============ */` 直接相邻。校验：`grep -c "purchaseNow\|accountInfo" app/static/high-fidelity-demo.js` 应为 0。

- [ ] **Step 3: 研究页按钮与状态（js:280、326）**

```js
旧: <small class="muted dim-status">●　未启动</small></div><button class="btn small dim-start" type="button" data-dim="'+key+'">启动分析</button>
新: <small class="muted dim-status">●　未开始</small></div><button class="btn small dim-start" type="button" data-dim="'+key+'">开始分析</button>

旧:     var label='●　未启动',button='启动分析';
新:     var label='●　未开始',button='开始分析';
```

注意：● 后为全角空格（U+3000），保持原样。

- [ ] **Step 4: 研究页回答/证据文案（js:352、358、378、418）**

```js
旧: <p>AI 正在读取证据快照并生成主回答…</p>
新: <p>正在整理相关证据并生成回答…</p>

旧: 结果已保存到当前研究会话与 run；刷新或重进会话仍可查看。
新: 结果已保存至本次研究记录；刷新或重新进入仍可查看。

旧:       pa.textContent=detailStatus==='running'?'详细回答生成中…':(detailStatus==='completed'?'重新生成详细回答':(detailStatus==='failed'?'详细回答失败，重试':'生成详细回答'));
新:       pa.textContent=detailStatus==='running'?'完整报告生成中…':(detailStatus==='completed'?'重新生成完整报告':(detailStatus==='failed'?'完整报告生成失败，重试':'生成完整报告'));

旧: <p>正在识别股票并建立证据快照…</p>
新: <p>正在识别股票并整理相关证据…</p>
```

- [ ] **Step 5: 个人中心运行时文案（js:1206 单行内五处子串替换）**

```js
旧: <p class="muted">仅展示当前会话的研究资产，不展示虚构积分、会员或资产余额。</p>
新: <p class="muted">这里仅展示你的研究资产；会员、积分与支付功能尚未开放。</p>

旧: <div>◔<span>研究运行</span>
新: <div>◔<span>研究记录</span>

旧: <p class="footer-note">数据来自当前会话的后端聚合接口。</p>
新: <p class="footer-note">仅统计你在当前账户下的研究资产。</p>

旧: 自选、对话、研究运行和上传资料仅属于当前会话；行情与基础证券数据由后台共享缓存刷新，不会因进入个人空间重新启动。
新: 你的关注、研究记录与上传资料仅保存在当前账户空间；行情数据由平台统一更新。

旧: 支付宝支付尚未开放，只会创建不可支付的订单草稿。
新: 支付宝支付尚未开放。
```

- [ ] **Step 6: 删除创建订单草稿入口（js:1207 整行删除）**

删除以 `      page.insertAdjacentHTML('beforeend','<article class="card" style="margin-top:12px;padding:16px 18px"><h3>支付宝订单预留</h3>` 开头的整行物理行（行尾为 `orderDraftButton.disabled=false})});`）。校验：`grep -c "profileOrderDraft\|支付宝订单预留\|创建订单草稿" app/static/high-fidelity-demo.js` 应为 0。

- [ ] **Step 7: 市场复盘（js:1228、1230）**

```js
旧: (data.generation_mode==='llm_evidence_clustering'?'模型仅执行证据聚类':'确定性证据摘录')
新: (data.generation_mode==='llm_evidence_clustering'?'AI 整理':'平台整理')

旧: available?'已获取 '+(state.items||0)+' 条':'当前不可用，不参与结论'
新: available?'已获取 '+(state.items||0)+' 条':'本期未纳入该来源数据'

旧: '+(available?(state.items||0)+'条':'未接通')+'</span>'
新: '+(available?(state.items||0)+'条':'本期未纳入')+'</span>'
```

- [ ] **Step 8: 校验与提交**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -c "启动分析\|生成详细回答\|证据快照\|随 run 保存\|研究会话与 run\|模型仅执行证据聚类\|确定性证据摘录\|未接通\|虚构积分\|研究运行\|共享缓存刷新\|数据来自当前会话\|创建订单草稿\|purchaseNow\|accountInfo" app/static/high-fidelity-demo.js   # 预期 0
git add app/static/high-fidelity-demo.js
git commit -m "feat(copy): 研究/关注/复盘/个人中心文案清理，隐藏订单草稿入口并删除死代码"
```

## Task 4: CSS 三处小修 + 死样式删除

**Files:** Modify `app/static/high-fidelity-demo.css`

**提交策略（有意夹带，已向用户报备）**：本文件工作树含用户预存改动（11+/8-：logo img、bar-chart 间距、stock-hero/industry-factor/assistant-copy/research-modal 微调、watch-search-result-row、market-review 样式、kline-zoom-controls、source-mark 变体、响应式调整），与已上线功能配套，随本任务一并提交并在提交信息中溯源。

- [ ] **Step 1: 三处小修（子串替换，均在超长单行内）**

```css
旧: .price-chart{cursor:zoom-in;touch-action:none}
新: .price-chart{cursor:grab;touch-action:none}

旧: background:#ef2929
新: background:var(--red)

旧: .btn{border:1px solid #cbd9ed;
新: .btn{border:1px solid var(--line);
```

- [ ] **Step 2: 删除死样式（两个整行物理行）**

- 删除以 `    .purchase-card{padding:16px 20px}` 开头的整行（含 `.purchase-*/.payment-*` 全部规则，行尾为 `.payment-security:before{content:"♢";color:#8aa6d2;margin-right:5px}`）
- 删除行 `    @media(max-width:820px){.purchase-layout{grid-template-columns:1fr;gap:20px}.payment-box{border-left:0;border-top:1px solid var(--line);padding:18px 0 0}}`

- [ ] **Step 3: 校验与提交**

```bash
grep -c "purchase-\|payment-\|zoom-in\|#ef2929\|#cbd9ed" app/static/high-fidelity-demo.css   # 预期 0
grep -c "cursor:grab" app/static/high-fidelity-demo.css   # 预期 1
git add app/static/high-fidelity-demo.css
git commit -m "feat(style): K线光标改 grab、颜色收敛至 token，删除购买死样式

夹带溯源：本提交含工作树预存的用户视觉微调（logo img、market-review、
kline-zoom-controls、source-mark 等 11+/8-），与已上线功能配套，经用户批准。"
```

## Task 5: 控制器验证（不派发实现者）

1. `node --check` 两个 JS 文件。
2. 残留 grep（用户术语全清单，逐条人工裁决命中是否为代码标识符/注释）：真实数据、真实行情、未接通、后端聚合接口、证据快照、模型仅执行证据聚类、确定性证据摘录、共享缓存刷新、数据来自当前会话、创建订单草稿、虚构积分、研究运行、可选增强、三天有效、三天一更、Tavily、启动分析、生成详细回答、加入关注、关键词直达、行业AI精选、AI筛选、AI赋能投研、七页交互演示、演示数据已导出、已打开收藏夹、设置面板已打开、更多 ›。
3. CDP 六页截图 + Console 零报错：重点个人中心（无演示内容闪现）、AI研究（新按钮文案）、复盘（示例数据标注）、评分库（pill 新文案）、今日观察（页脚）。
4. 后端 pytest 全量（预期 454 passed 不变）。
