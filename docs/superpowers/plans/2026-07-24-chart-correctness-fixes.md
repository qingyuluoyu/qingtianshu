# 图表正确性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `high-fidelity-demo.js` 中图表的 4 类问题：MA 均线边缘计算错误、雷达图标签溢出、`marketLine` 死代码、涨跌色板不统一。

**Architecture:** 单文件修改（`app/static/high-fidelity-demo.js`），不改 HTML/CSS，不引入依赖，不加新交互。仓库无 JS 测试框架，TDD 适配为：`node --check` 语法校验 + 浏览器实测验证（含确定性合成数据兜底）。

**Tech Stack:** 原生 Canvas 2D / 手写图表；FastAPI（`app/main.py`）提供 `/static/` 静态服务；node v24 用于语法校验。

**参照 spec:** `docs/superpowers/specs/2026-07-24-chart-correctness-fixes-design.md`

## Global Constraints

- 仅修改 `app/static/high-fidelity-demo.js`；不改 `high-fidelity-demo.html` / `high-fidelity-demo.css`；不新增文件、不引入任何库。
- 色板常量固定（verbatim）：`CHART_UP_RED='#f3262d'`、`CHART_DOWN_GREEN='#079a56'`、`CHART_FLAT_GRAY='#bcc3ce'`、`CHART_PRIMARY_BLUE='#1768ef'`、`CHART_COMPARE_GREEN='#10a25d'`。
- 代码风格照原文件：ES5 `var`、函数声明、逗号链单语句、两空格缩进。
- 文中行号以修改前原文件为参照；实际编辑一律用**精确字符串匹配**（行号会随任务推进漂移）。
- 每个任务结束：`node --check` 通过 → 浏览器验证通过 → 独立 commit。
- 开始 Task 1 前，先阅读 dataviz 技能（触发条件：写图表代码前必读），若其规范与本计划色板/标注冲突，以本计划已批准的 spec 为准并记录差异。
- 明确不动：`watchStatusColors`（关注状态语义）、成交量 `rgba(243,38,45,.72)`/`rgba(7,154,86,.72)`（alpha 变体）、雷达 `rgba(16,162,93,.07)`/`rgba(23,104,239,.11)` 填充、MA20 紫 `#795add`、`#72a7f5`（行业中位蓝）、成交活跃度渐变 `#2076fa/#0e62eb`、空 donut `#e5e9ef`、HTML 内联 legend 色、CSS 文件。

---

### Task 1: 统一涨跌色板常量

**Files:**
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: 无
- Produces: 常量 `CHART_UP_RED`、`CHART_DOWN_GREEN`、`CHART_FLAT_GRAY`、`CHART_PRIMARY_BLUE`、`CHART_COMPARE_GREEN`（IIFE 顶部作用域，后续所有任务可用）

- [ ] **Step 0: 阅读 dataviz 技能**

调用 Skill 工具读取 `dataviz` 技能。本计划色板已经 spec 批准，仅核对其标注规范有无必须记录的差异；不因此改动计划。

- [ ] **Step 1: 在 IIFE 顶部定义色板常量**

在原文件 L33 行：

```js
  var toastTimer,profilePageRequested=false,todayPageRequested=false,marketReviewPageRequested=false;
```

之后插入一行：

```js
  /* 图表统一色板：上涨红/下跌绿/平盘灰/主题蓝/对比系列绿（COMPARE_GREEN 仅用于行业中位等对比系列，与下跌绿区分语义） */
  var CHART_UP_RED='#f3262d',CHART_DOWN_GREEN='#079a56',CHART_FLAT_GRAY='#bcc3ce',CHART_PRIMARY_BLUE='#1768ef',CHART_COMPARE_GREEN='#10a25d';
```

- [ ] **Step 2: 替换 10 处色值字面量**

逐条精确字符串替换（顺序无关）：

① `todayRenderers.indices`（约 L682）：

```js
// 旧
if(canvas&&Array.isArray(item.trend)&&item.trend.length>1){canvas.setAttribute('data-points',item.trend.join(','));canvas.setAttribute('data-color',change>=0?'#f3262d':'#079a56');line(canvas,item.trend,change>=0?'#f3262d':'#079a56',true)}
// 新
if(canvas&&Array.isArray(item.trend)&&item.trend.length>1){canvas.setAttribute('data-points',item.trend.join(','));canvas.setAttribute('data-color',change>=0?CHART_UP_RED:CHART_DOWN_GREEN);line(canvas,item.trend,change>=0?CHART_UP_RED:CHART_DOWN_GREEN,true)}
```

② `todayRenderers.marketOverview` donut（约 L690，平盘灰 `#d6dbe4` 一并统一为 `CHART_FLAT_GRAY`，视觉略加深属预期）：

```js
// 旧
donut.style.background='conic-gradient(#f3262d 0 '+risingRate+'%,#d6dbe4 '+risingRate+'% '+flatEnd+'%,#079a56 '+flatEnd+'% 100%)';
// 新
donut.style.background='conic-gradient('+CHART_UP_RED+' 0 '+risingRate+'%,'+CHART_FLAT_GRAY+' '+risingRate+'% '+flatEnd+'%,'+CHART_DOWN_GREEN+' '+flatEnd+'% 100%)';
```

③ `todayRenderers.industryRotation`（约 L694）：

```js
// 旧
data-color="'+(change>=0?'#f3262d':'#079a56')+'"
// 新
data-color="'+(change>=0?CHART_UP_RED:CHART_DOWN_GREEN)+'"
```

④ `drawTopMetricComparison` 配色（约 L863）：

```js
// 旧
colors=['#1768ef','#72a7f5','#10a25d'];
// 新
colors=[CHART_PRIMARY_BLUE,'#72a7f5',CHART_COMPARE_GREEN];
```

⑤ K线蜡烛（约 L1087）：

```js
// 旧
color=row.close>=row.open?'#f3262d':'#079a56'
// 新
color=row.close>=row.open?CHART_UP_RED:CHART_DOWN_GREEN
```

⑥ MA 线色（约 L1088；MA10 `#2774ed` 统一为 `CHART_PRIMARY_BLUE`）：

```js
// 旧
[[5,'#f3262d'],[10,'#2774ed'],[20,'#795add']].forEach(function(def){
// 新
[[5,CHART_UP_RED],[10,CHART_PRIMARY_BLUE],[20,'#795add']].forEach(function(def){
```

⑦ `radar()` 系列色（约 L1146）：

```js
// 旧
if(values2)area(values2,'#10a25d','rgba(16,162,93,.07)');area(values,'#1768ef','rgba(23,104,239,.11)')
// 新
if(values2)area(values2,CHART_COMPARE_GREEN,'rgba(16,162,93,.07)');area(values,CHART_PRIMARY_BLUE,'rgba(23,104,239,.11)')
```

⑧ 市场复盘指数 spark（约 L1194）：

```js
// 旧
line(canvas,points,Number(item.changePct)>=0?'#f3262d':'#079a56',false)
// 新
line(canvas,points,Number(item.changePct)>=0?CHART_UP_RED:CHART_DOWN_GREEN,false)
```

⑨ 市场结构 donut（约 L1199，平盘灰 `#cfd6e1` 统一为 `CHART_FLAT_GRAY`）：

```js
// 旧
style="background:conic-gradient(#f3262d 0 '+riseRate+'%,#cfd6e1 '+riseRate+'% '+fallStart+'%,#079a56 '+fallStart+'% 100%)
// 新
style="background:conic-gradient('+CHART_UP_RED+' 0 '+riseRate+'%,'+CHART_FLAT_GRAY+' '+riseRate+'% '+fallStart+'%,'+CHART_DOWN_GREEN+' '+fallStart+'% 100%)
```

⑩ `drawAll` sparkline 默认色（约 L1153）：

```js
// 旧
cv.getAttribute('data-color')||'#1768ef'
// 新
cv.getAttribute('data-color')||CHART_PRIMARY_BLUE
```

- [ ] **Step 3: 语法校验 + 残留检查**

```bash
cd "F:\tools\3.3 realyy\3.4html展示\3.4html展示\qingtianshu-main\qingtianshu-main"
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "'#f3262d'\|'#079a56'\|'#2774ed'\|'#1768ef'\|'#10a25d'\|'#d6dbe4'\|'#cfd6e1'" app/static/high-fidelity-demo.js
```

预期：`SYNTAX_OK`；grep 输出**恰好两行**——① 常量声明行 `var CHART_UP_RED='#f3262d',...`（字面量的合法来源）；② `marketLine` 函数体内的 `'#1768ef'`（Task 2 将连同该死代码一并删除，本任务不动）。除这两行外不得有任何其他匹配。

- [ ] **Step 4: 浏览器冒烟验证**

```bash
cd "F:\tools\3.3 realyy\3.4html展示\3.4html展示\qingtianshu-main\qingtianshu-main"
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

（后台启动；若已有服务占用 8000 则直接复用。）浏览器打开 `http://127.0.0.1:8000/static/high-fidelity-demo.html`：

- 今日观察页：4 张指数 sparkline、市场总览 donut、行业轮动 mini-line 正常渲染，颜色与之前一致（donut 平盘灰略深为预期）
- 个股评分库页：K线蜡烛红涨绿跌、MA 三线颜色正常（MA10 蓝与之前肉眼无差异）
- DevTools Console 无报错

- [ ] **Step 5: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "refactor(charts): 统一涨跌色板为 CHART_* 常量"
```

---

### Task 2: 删除 marketLine 与 grid 死代码

**Files:**
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: 无
- Produces: 无（纯删除）。删除后 `drawAll()` 不再调用 `marketLine()`。

- [ ] **Step 1: 删除 marketLine 函数及其调用**

删除整个函数（约 L1148-1151）：

```js
  function marketLine(){
    var cv=$('#marketLine');if(!cv||!cv.offsetParent)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p=20;grid(c,w,h,p);var a=[45,55,43,52,41,59,47],b=[9000,11000,9700,10500,9200,13000,11200];
    [[a,'#1768ef'],[b,'#08a05a']].forEach(function(d){var min=Math.min.apply(null,d[0]),max=Math.max.apply(null,d[0]),range=max-min||1;c.beginPath();d[0].forEach(function(v,i){var x=p+i*(w-p*2)/(d[0].length-1),y=h-p-(v-min)*(h-p*2)/range;i?c.lineTo(x,y):c.moveTo(x,y)});c.strokeStyle=d[1];c.lineWidth=2;c.stroke();d[0].forEach(function(v,i){var x=p+i*(w-p*2)/(d[0].length-1),y=h-p-(v-min)*(h-p*2)/range;c.fillStyle=d[1];c.beginPath();c.arc(x,y,3,0,Math.PI*2);c.fill()})})
  }
```

并修改 `drawAll()`（约 L1154），去掉末尾对 `marketLine()` 的调用：

```js
// 旧
$$('.radar').forEach(radar);drawTopMetricComparison();priceChart();volumeChart();marketLine()
// 新
$$('.radar').forEach(radar);drawTopMetricComparison();priceChart();volumeChart()
```

- [ ] **Step 2: 删除 grid 函数**

`grid()`（约 L478）仅被 `marketLine` 调用，删除后成为死代码，一并删除：

```js
  function grid(c,w,h,pad){c.strokeStyle='#e7edf6';c.lineWidth=1;for(var i=1;i<5;i++){var y=pad+i*(h-pad*2)/5;c.beginPath();c.moveTo(pad,y);c.lineTo(w-pad,y);c.stroke()}}
```

- [ ] **Step 3: 语法校验 + 残留检查**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "marketLine\|function grid\|grid(c" app/static/high-fidelity-demo.js || echo NO_DEAD_CODE
```

预期：`SYNTAX_OK`；`NO_DEAD_CODE`。

- [ ] **Step 4: 浏览器冒烟验证**

刷新 `http://127.0.0.1:8000/static/high-fidelity-demo.html`，逐页切换（今日/评分/研究/关注/复盘/我的），各图表正常渲染，Console 无 `ReferenceError` 等报错。

- [ ] **Step 5: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "chore(charts): 删除未生效的 marketLine/grid 死代码"
```

---

### Task 3: MA 均线改为全量计算后切片（修正确性）

**Files:**
- Modify: `app/static/high-fidelity-demo.js`（`priceChart()` 函数）

**Interfaces:**
- Consumes: `klineState.data`（全量 K 线数组）、`visibleKlineRows()`（可见切片）、`movingAverage(rows, size)`（既有，返回等长含 `null` 的数组）、Task 1 的 `CHART_UP_RED`/`CHART_PRIMARY_BLUE`
- Produces: 无新接口；`priceChart()` 行为变化——MA 值与缩放窗口无关

- [ ] **Step 1: 在 priceChart 变量链中加入全量数据与偏移量**

```js
// 旧
p={l:48,r:12,t:12,b:25},rows=visibleKlineRows(),plotW=w-p.l-p.r,
// 新
p={l:48,r:12,t:12,b:25},rows=visibleKlineRows(),allRows=klineState.data,maOffset=allRows.length-rows.length,plotW=w-p.l-p.r,
```

- [ ] **Step 2: MA 绘制循环改为全量计算 + 切片**

```js
// 旧
[[5,CHART_UP_RED],[10,CHART_PRIMARY_BLUE],[20,'#795add']].forEach(function(def){var values=movingAverage(rows,def[0]),started=false;
// 新
[[5,CHART_UP_RED],[10,CHART_PRIMARY_BLUE],[20,'#795add']].forEach(function(def){var values=movingAverage(allRows,def[0]).slice(maOffset),started=false;
```

（循环体其余部分不变：`values.forEach` 内 `null` 跳过、`x=p.l+step*(i+.5)` 定位均保持原样。）

- [ ] **Step 3: 语法校验**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
```

- [ ] **Step 4: 浏览器验证（真实行情优先，合成数据兜底）**

方式 A（后端行情可用时）：打开个股评分库页，连续点击 K线「−」缩小到最少 12 根。
**预期（修复效果）**：MA20 紫色均线**贯穿整个图表宽度**；修复前 12 根窗口下 MA20 全为 `null`、紫线完全消失。MA5/MA10/MA20 标注值不随缩放跳动。

方式 B（行情接口不可用时的确定性兜底）：DevTools Console 注入合成数据：

```js
window.QSMarketAPI.fetchKline=function(params){var rows=[],t=new Date('2026-04-01').getTime(),price=190;for(var i=0;i<80;i++){price+=Math.sin(i/3)*1.5;var o=price;rows.push({time:new Date(t+i*86400000).toISOString().slice(0,10),open:o,high:o+1.2,low:o-1.2,close:o+0.6,volume:1000000+i*10000})}return Promise.resolve(rows)};
QSReloadKline({period:'1d'});
```

再点「−」到 12 根，同样验证紫线贯穿全宽；「重置」后三线形态不变。

- [ ] **Step 5: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "fix(charts): MA均线按全量K线计算后切片，修复缩放窗口左边缘数值错误"
```

---

### Task 4: 雷达图标签防溢出

**Files:**
- Modify: `app/static/high-fidelity-demo.js`（`radar()` 函数）

**Interfaces:**
- Consumes: 既有 `radar(cv)` 内局部变量 `labels/n/cx/cy/r/w/h/c`、`point(i,rr)` 辅助函数
- Produces: 无新接口；`radar()` 行为变化——标签按角度对齐并钳制在画布内。`#industryFactorRadar` 与 `#marketReviewRadar` 共用此函数，同时修复。

- [ ] **Step 1: 重写标签绘制循环**

在 `radar()` 中（约 L1144）：

```js
// 旧
for(var j=0;j<n;j++){var end=point(j,r);c.beginPath();c.moveTo(cx,cy);c.lineTo(end[0],end[1]);c.strokeStyle='#e5ebf4';c.stroke();var lp=point(j,r+22);c.fillStyle='#344a6a';c.fillText(labels[j],lp[0],lp[1])}
// 新
for(var j=0;j<n;j++){var end=point(j,r);c.beginPath();c.moveTo(cx,cy);c.lineTo(end[0],end[1]);c.strokeStyle='#e5ebf4';c.stroke();
  var cosA=Math.cos(-Math.PI/2+j*Math.PI*2/n),lp=point(j,r+22),label=labels[j],tw=c.measureText(label).width;
  c.textAlign=cosA>.3?'left':cosA<-.3?'right':'center';
  var lx=lp[0];if(c.textAlign==='left')lx=Math.max(6,Math.min(lx,w-6-tw));else if(c.textAlign==='right')lx=Math.min(w-6,Math.max(lx,6+tw));else lx=Math.max(6+tw/2,Math.min(w-6-tw/2,lx));
  var ly=Math.max(10,Math.min(h-10,lp[1]));
  c.fillStyle='#344a6a';c.fillText(label,lx,ly)}
c.textAlign='center';
```

说明：角度余弦 >0.3 的轴文本左对齐、<-0.3 右对齐、否则居中；锚点经 `measureText` 换算后钳制在 `[6, w-6]`/`[10, h-10]` 内，文本边界不越出画布。循环结束恢复 `textAlign='center'` 避免影响后续绘制状态。

- [ ] **Step 2: 语法校验**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
```

- [ ] **Step 3: 浏览器验证**

- 个股评分库 → 五维行业对比雷达（标签：成长性/估值水平/盈利能力/财务稳健性/经营效率）：五个标签**完整显示无裁切**，"财务稳健性"等长标签不再越出画布左右边缘
- 股票复盘 → 大盘/市场复盘 → 本周市场复盘概述雷达（标签：赚钱效应/资金面/情绪面/风险水平/趋势强度）：同样完整
- 拖窄浏览器窗口触发重绘，标签仍不越界

- [ ] **Step 4: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "fix(charts): 雷达图标签按角度对齐并钳制画布内，修复长标签裁切"
```

---

### Task 5: 端到端回归验证

**Files:**
- 无修改（纯验证任务）

**Interfaces:**
- Consumes: Task 1-4 的全部改动
- Produces: 验证结论（通过/问题清单）

- [ ] **Step 1: 静态检查汇总**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "marketLine\|function grid\|'#f3262d'\|'#079a56'\|'#2774ed'\|'#1768ef'\|'#10a25d'\|'#d6dbe4'\|'#cfd6e1'" app/static/high-fidelity-demo.js | grep -v "var CHART_UP_RED" || echo ALL_CLEAN
grep -n "CHART_UP_RED\|CHART_DOWN_GREEN\|CHART_FLAT_GRAY\|CHART_PRIMARY_BLUE\|CHART_COMPARE_GREEN" app/static/high-fidelity-demo.js | head -25
```

预期：`SYNTAX_OK`、`ALL_CLEAN`（唯一合法残留——常量声明行——已被第二段 grep 排除）；常量引用点 ≥15 处。

- [ ] **Step 2: 六页全量回归**

刷新页面（强刷 `Ctrl+F5` 清缓存），逐页检查：

| 页面 | 检查点 |
|---|---|
| 今日观察 | 4 指数卡 sparkline、总览 donut、涨跌结构柱、成交活跃柱、行业轮动 mini-line、板块净流入条 |
| 个股评分库 | K线缩放/周期切换/放大还原，MA 三线 + 标注，估值对比分组柱，五维雷达标签完整 |
| AI研究 | 无图表，确认无 Console 报错即可 |
| 我的关注 | 状态分布 donut + legend 正常 |
| 股票复盘 | 市场复盘：指数 spark、结构 donut、复盘雷达标签完整 |
| 个人中心 | 无图表，确认无 Console 报错 |

- [ ] **Step 3: Console 零报错确认**

DevTools Console 过滤 Error 级别，六页切换后无任何红色报错（后端数据接口 4xx/5xx 网络告警若存在，与本次改动无关，记录但不阻塞）。

- [ ] **Step 4: 无需 commit**

本任务无代码改动。在最终汇报中给出验证结论。
