# 图表交互增强与模块化 Implementation Plan（第二轮）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** K线十字光标+悬浮详情、K线拖拽平移历史、雷达顶点数值标注、图表引擎抽离 `qs-charts.js`、清理 `pendingDraw` 死状态。

**Architecture:** 新建零依赖 `app/static/qs-charts.js`（`window.QSCharts` 暴露 colors/setup/line/radar），主文件 `high-fidelity-demo.js` 通过一行别名零改动保留既有调用点；HTML 仅新增一个 defer script 标签。仓库无 JS 测试框架，TDD 适配为 `node --check` + grep 静态校验（每任务）+ 控制器统一 CDP 浏览器验证（Task 5）。

**Tech Stack:** 原生 Canvas 2D；FastAPI `/static/` 静态服务；node v24 语法校验；CDP 无头 Edge（harness 已建于第一轮）。

**参照 spec:** `docs/superpowers/specs/2026-07-24-chart-interactions-design.md`

## Global Constraints

- 代码风格照原文件：ES5 `var`、函数声明、逗号链单语句、两空格缩进。
- 行号参照**第一轮完成后**的文件状态（commit `44fc456`）；实际编辑一律用**精确字符串匹配**。
- `CHART_*` 色值原值迁移不得改值：`up:'#f3262d'`、`down:'#079a56'`、`flat:'#bcc3ce'`、`primary:'#1768ef'`、`compare:'#10a25d'`。
- HTML 仅允许新增一行 `<script src="/static/qs-charts.js" defer></script>`（必须在 demo 脚本之前）；不动 CSS 文件；不动后端。
- 跨任务接口签名固定：`window.QSCharts={colors,setup,line,radar}`；`klineState.panOffset`（number，距右端偏移柱数）；`klineState.crosshair`（`null|{index,y}`）；`klineDrag`（IIFE 内 var，拖拽中 truthy）。
- 每个任务结束：`node --check` 通过 → 独立 commit（只 add 本计划点名的文件；工作树有大量无关预存改动，严禁一并提交）。
- 浏览器验证一律由控制器在 Task 5 批量执行，实现者不得启动服务器。
- 旧字符串不匹配时 STOP 并报告实际上下文，禁止即兴替换。

---

### Task 1: 抽离 qs-charts.js + 清理 pendingDraw

**Files:**
- Create: `app/static/qs-charts.js`
- Modify: `app/static/high-fidelity-demo.js`
- Modify: `app/static/high-fidelity-demo.html`（仅一行 script 标签）

**Interfaces:**
- Consumes: 无
- Produces: `window.QSCharts={colors:{up,down,flat,primary,compare},setup(canvas),line(canvas,points,color,fill),radar(canvas)}`；主文件别名 `var setup=QSCharts.setup,line=QSCharts.line,radar=QSCharts.radar;`（后续任务与既有调用点均依赖别名零改动）

- [ ] **Step 1: 创建 `app/static/qs-charts.js`，完整内容如下**

```js
/* qs-charts.js — 清数智算图表引擎层：统一色板与共用 canvas 绘制函数。
 * 通过 window.QSCharts 暴露；须在 high-fidelity-demo.js 之前加载（均为 defer，按文档顺序执行）。 */
window.QSCharts=(function(){
  var colors={up:'#f3262d',down:'#079a56',flat:'#bcc3ce',primary:'#1768ef',compare:'#10a25d'};
  function setup(canvas){var r=window.devicePixelRatio||1,w=canvas.clientWidth||300,h=canvas.clientHeight||120;canvas.width=w*r;canvas.height=h*r;var c=canvas.getContext('2d');c.setTransform(r,0,0,r,0,0);c.clearRect(0,0,w,h);return {c:c,w:w,h:h}}
  function line(canvas,points,color,fill){
    if(!canvas.offsetParent)return;var s=setup(canvas),c=s.c,w=s.w,h=s.h,arr=points.map(Number),min=Math.min.apply(null,arr),max=Math.max.apply(null,arr),range=max-min||1,pad=4;
    c.beginPath();arr.forEach(function(v,i){var x=pad+i*(w-pad*2)/(arr.length-1),y=h-pad-(v-min)*(h-pad*2)/range;i?c.lineTo(x,y):c.moveTo(x,y)});
    c.strokeStyle=color;c.lineWidth=2;c.lineJoin='round';c.lineCap='round';c.stroke();
    if(fill){c.lineTo(w-pad,h-pad);c.lineTo(pad,h-pad);c.closePath();var g=c.createLinearGradient(0,0,0,h);g.addColorStop(0,color+'2e');g.addColorStop(1,color+'00');c.fillStyle=g;c.fill()}
  }
  function radar(cv){
    if(!cv.offsetParent)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,labels=(cv.getAttribute('data-labels')||'A,B,C,D,E').split(','),values=(cv.getAttribute('data-values')||'80,80,80,80,80').split(',').map(Number),values2=cv.getAttribute('data-values2')?cv.getAttribute('data-values2').split(',').map(Number):null,n=labels.length,cx=w/2,cy=h/2+4,r=Math.min(w,h)*.32;
    function point(i,rr){var a=-Math.PI/2+i*Math.PI*2/n;return [cx+Math.cos(a)*rr,cy+Math.sin(a)*rr]}
    c.font='11px Microsoft YaHei';c.textAlign='center';c.textBaseline='middle';
    for(var level=1;level<=5;level++){c.beginPath();for(var i=0;i<n;i++){var pt=point(i,r*level/5);i?c.lineTo(pt[0],pt[1]):c.moveTo(pt[0],pt[1])}c.closePath();c.strokeStyle='#dfe7f3';c.stroke()}
    for(var j=0;j<n;j++){var end=point(j,r);c.beginPath();c.moveTo(cx,cy);c.lineTo(end[0],end[1]);c.strokeStyle='#e5ebf4';c.stroke();
      var cosA=Math.cos(-Math.PI/2+j*Math.PI*2/n),lp=point(j,r+22),label=labels[j],tw=c.measureText(label).width;
      c.textAlign=cosA>.3?'left':cosA<-.3?'right':'center';
      var lx=lp[0];if(c.textAlign==='left')lx=Math.max(6,Math.min(lx,w-6-tw));else if(c.textAlign==='right')lx=Math.min(w-6,Math.max(lx,6+tw));else lx=Math.max(6+tw/2,Math.min(w-6-tw/2,lx));
      var ly=Math.max(10,Math.min(h-10,lp[1]));
      c.fillStyle='#344a6a';c.fillText(label,lx,ly)}
    c.textAlign='center';
    function area(vals,color,fill){c.beginPath();vals.forEach(function(v,i){var pnt=point(i,r*v/100);i?c.lineTo(pnt[0],pnt[1]):c.moveTo(pnt[0],pnt[1])});c.closePath();c.fillStyle=fill;c.fill();c.strokeStyle=color;c.lineWidth=2;c.stroke();vals.forEach(function(v,i){var pnt=point(i,r*v/100);c.fillStyle=color;c.beginPath();c.arc(pnt[0],pnt[1],2.4,0,Math.PI*2);c.fill()})}
    if(values2)area(values2,colors.compare,'rgba(16,162,93,.07)');area(values,colors.primary,'rgba(23,104,239,.11)')
  }
  return {colors:colors,setup:setup,line:line,radar:radar};
})();
```

注意：这是主文件 `setup`/`line`/`radar` 三个函数的原样迁移，唯一差别是 `radar` 内的 `CHART_COMPARE_GREEN`→`colors.compare`、`CHART_PRIMARY_BLUE`→`colors.primary`（值不变）。

- [ ] **Step 2: 主文件——常量行改为别名（约 L35）**

```js
// 旧
  var CHART_UP_RED='#f3262d',CHART_DOWN_GREEN='#079a56',CHART_FLAT_GRAY='#bcc3ce',CHART_PRIMARY_BLUE='#1768ef',CHART_COMPARE_GREEN='#10a25d';
// 新
  var CHART_UP_RED=QSCharts.colors.up,CHART_DOWN_GREEN=QSCharts.colors.down,CHART_FLAT_GRAY=QSCharts.colors.flat,CHART_PRIMARY_BLUE=QSCharts.colors.primary,CHART_COMPARE_GREEN=QSCharts.colors.compare;
  var setup=QSCharts.setup,line=QSCharts.line,radar=QSCharts.radar;
```

- [ ] **Step 3: 主文件——删除三个已迁移的函数**

删除 `function setup(...)`（约 L473，单行函数）、`function line(...)`（约 L474-479，含闭合 `}` 共 6 行）、`function radar(...)`（约 L1140-1154，含闭合 `}` 共 15 行）。三个函数体与 Step 1 中 qs-charts.js 的内容逐一对应（除 radar 内两处颜色引用名）；删除后主文件不得再出现 `function setup(`、`function line(`、`function radar(`。

- [ ] **Step 4: 主文件——清理 pendingDraw（约 L766、L860-861）**

```js
// 旧
  var topMetricComparisonState={series:[],pendingDraw:false};
// 新
  var topMetricComparisonState={series:[]};
```

```js
// 旧
    if(!cv||!cv.offsetParent){topMetricComparisonState.pendingDraw=true;return}
    topMetricComparisonState.pendingDraw=false;
// 新
    if(!cv||!cv.offsetParent)return;
```

- [ ] **Step 5: HTML——新增 script 标签**

```html
<!-- 旧 -->
  <script src="/static/high-fidelity-demo.js" defer></script>
<!-- 新 -->
  <script src="/static/qs-charts.js" defer></script>
  <script src="/static/high-fidelity-demo.js" defer></script>
```

- [ ] **Step 6: 静态校验**

```bash
cd "F:\tools\3.3 realyy\3.4html展示\3.4html展示\qingtianshu-main\qingtianshu-main"
node --check app/static/qs-charts.js && node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "function setup(\|function line(\|function radar(\|pendingDraw" app/static/high-fidelity-demo.js || echo MAIN_CLEAN
grep -n "qs-charts.js" app/static/high-fidelity-demo.html
```

预期：`SYNTAX_OK`；`MAIN_CLEAN`；HTML 有一行 qs-charts.js 引用且在 demo 脚本之前。

- [ ] **Step 7: Commit**

```bash
git add app/static/qs-charts.js app/static/high-fidelity-demo.js app/static/high-fidelity-demo.html
git commit -m "refactor(charts): 抽离qs-charts.js图表引擎层，清理pendingDraw死状态"
```

---

### Task 2: K线视口泛化 {count, panOffset} + 拖拽平移

**Files:**
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: 无（不依赖 Task 1 的别名，纯主文件内部改动）
- Produces: `klineState.panOffset`（number，默认 0，距右端偏移柱数）；`klineDrag`（IIFE 内 var，拖拽中为对象 `{x,pan,moved}`，否则 null——Task 3 用来抑制十字光标）；`visibleKlineRows()` 新切片逻辑（Task 3 也调用）

- [ ] **Step 1: klineState 增加 panOffset（约 L1017）**

```js
// 旧
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0,visibleBars:null,statusText:''};
// 新
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0,visibleBars:null,panOffset:0,statusText:''};
```

- [ ] **Step 2: visibleKlineRows 泛化（约 L1069-1072）**

```js
// 旧
  function visibleKlineRows(){
    var count=klineState.visibleBars===null?defaultVisibleBars():Math.max(12,Math.min(klineState.visibleBars,klineState.data.length));
    return klineState.data.slice(-count);
  }
// 新
  function visibleKlineRows(){
    var count=klineState.visibleBars===null?defaultVisibleBars():Math.max(12,Math.min(klineState.visibleBars,klineState.data.length));
    var end=Math.max(0,klineState.data.length-(klineState.panOffset||0)),start=Math.max(0,end-count);
    return klineState.data.slice(start,end);
  }
```

- [ ] **Step 3: priceChart 的 maOffset 泛化（约 L1084，与 Step 2 的切片对齐）**

```js
// 旧
rows=visibleKlineRows(),allRows=klineState.data,maOffset=allRows.length-rows.length,
// 新
rows=visibleKlineRows(),allRows=klineState.data,maOffset=allRows.length-(klineState.panOffset||0)-rows.length,
```

（验证不变式：右锚定时 panOffset=0，本式 ≡ 旧式；平移后 maOffset 仍等于切片起点在全量中的下标。）

- [ ] **Step 4: renderKlineStatus 增加历史视图提示（约 L1076）**

```js
// 旧
    node.textContent=klineState.statusText+(count?' · 显示 '+count+' 根':'');
// 新
    node.textContent=klineState.statusText+(count?' · 显示 '+count+' 根':'')+((klineState.panOffset||0)>0?' · 历史视图（双击复位）':'');
```

- [ ] **Step 5: zoomKline 复位/钳制 panOffset（约 L1078-1082）**

```js
// 旧
  function zoomKline(direction){
    if(!klineState.data.length)return;
    var current=visibleKlineRows().length,next=direction==='reset'?defaultVisibleBars():Math.round(current*(direction==='in'?.72:1.38));
    klineState.visibleBars=Math.max(12,Math.min(klineState.data.length,next));renderKlineStatus();priceChart();volumeChart();
  }
// 新
  function zoomKline(direction){
    if(!klineState.data.length)return;
    var current=visibleKlineRows().length,next=direction==='reset'?defaultVisibleBars():Math.round(current*(direction==='in'?.72:1.38));
    klineState.visibleBars=Math.max(12,Math.min(klineState.data.length,next));
    klineState.panOffset=direction==='reset'?0:Math.max(0,Math.min(klineState.panOffset||0,klineState.data.length-klineState.visibleBars));
    renderKlineStatus();priceChart();volumeChart();
  }
```

- [ ] **Step 6: 换股票时复位（约 L948）**

```js
// 旧
if(klineState.symbol!==nextSymbol)klineState.visibleBars=null;
// 新
if(klineState.symbol!==nextSymbol){klineState.visibleBars=null;klineState.panOffset=0}
```

- [ ] **Step 7: 切周期时复位（约 L1104）**

```js
// 旧
klineState.period=period;klineState.loading=true;if(periodChanged)klineState.visibleBars=null;
// 新
klineState.period=period;klineState.loading=true;if(periodChanged){klineState.visibleBars=null;klineState.panOffset=0}
```

- [ ] **Step 8: 新增拖拽平移处理器（插入在 dblclick 注册行之后，约 L1136 后）**

```js
  var klineDrag=null,klineDragRaf=0;
  function klineStepPx(){var rows=visibleKlineRows();if(!rows.length)return 8;var cv=$('#priceChart'),w=cv?cv.clientWidth:600;return Math.max(2,(w-60)/rows.length)}
  $('#priceChart').addEventListener('mousedown',function(event){
    if(!klineState.data.length)return;event.preventDefault();
    klineDrag={x:event.clientX,pan:klineState.panOffset||0,moved:false};
  });
  window.addEventListener('mousemove',function(event){
    if(!klineDrag)return;
    var dx=event.clientX-klineDrag.x;if(Math.abs(dx)<3&&!klineDrag.moved)return;
    klineDrag.moved=true;klineState.crosshair=null;
    if(klineDragRaf)return;
    klineDragRaf=requestAnimationFrame(function(){
      klineDragRaf=0;if(!klineDrag)return;
      var maxOffset=Math.max(0,klineState.data.length-visibleKlineRows().length);
      klineState.panOffset=Math.max(0,Math.min(maxOffset,klineDrag.pan+Math.round((event.clientX-klineDrag.x)/klineStepPx())));
      renderKlineStatus();priceChart();volumeChart();
    });
  });
  window.addEventListener('mouseup',function(){if(klineDrag&&klineDrag.moved)priceChart();klineDrag=null});
```

（方向：dx>0 向右拖 → panOffset 增大 → 窗口左移看更早数据。`klineState.crosshair=null` 引用的属性由 Task 3 正式定义，此处赋值 null 无副作用。）

- [ ] **Step 9: 静态校验**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "panOffset" app/static/high-fidelity-demo.js | head -12
grep -n "slice(-count)" app/static/high-fidelity-demo.js || echo NO_RIGHT_ANCHOR
```

预期：`SYNTAX_OK`；panOffset 出现在 state/visibleKlineRows/priceChart/renderKlineStatus/zoomKline/loadStock/loadKline/拖拽块共 ≥8 处；`NO_RIGHT_ANCHOR`。

- [ ] **Step 10: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "feat(charts): K线视口泛化支持拖拽平移历史，历史视图带状态提示"
```

---

### Task 3: K线十字光标 + 悬浮详情

**Files:**
- Modify: `app/static/high-fidelity-demo.js`

**Interfaces:**
- Consumes: `klineDrag`（Task 2，拖拽中抑制十字光标）；`klineState.panOffset`（Task 2，定位前收）；`visibleKlineRows()`、`formatKlineTime`、`numberText`、`CHART_UP_RED/CHART_DOWN_GREEN`
- Produces: `klineState.crosshair`（`null|{index,y}`）；`drawKlineCrosshair()`；`redrawKlineWithCrosshair()`

- [ ] **Step 1: klineState 增加 crosshair 字段**

```js
// 旧（Task 2 后的状态行）
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0,visibleBars:null,panOffset:0,statusText:''};
// 新
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0,visibleBars:null,panOffset:0,crosshair:null,statusText:''};
```

- [ ] **Step 2: 新增十字光标绘制与事件（插入在 Task 2 的 mouseup 注册行之后）**

```js
  function chartCtx(cv){var r=window.devicePixelRatio||1,c=cv.getContext('2d');c.setTransform(r,0,0,r,0,0);return {c:c,w:cv.clientWidth,h:cv.clientHeight}}
  function redrawKlineWithCrosshair(){priceChart();volumeChart();drawKlineCrosshair()}
  function drawKlineCrosshair(){
    var st=klineState.crosshair;if(!st||!klineState.data.length)return;
    var rows=visibleKlineRows();if(!rows.length)return;
    var i=Math.max(0,Math.min(rows.length-1,st.index)),row=rows[i];
    var pcv=$('#priceChart');if(!pcv||!pcv.offsetParent)return;
    var s=chartCtx(pcv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:12,b:25},plotW=w-p.l-p.r,plotH=h-p.t-p.b,step=plotW/rows.length,x=p.l+step*(i+.5);
    var high=Math.max.apply(null,rows.map(function(r2){return r2.high})),low=Math.min.apply(null,rows.map(function(r2){return r2.low})),margin=(high-low)*.08||1;high+=margin;low-=margin;var range=high-low;
    c.setLineDash([4,3]);c.strokeStyle='#8b99ad';c.lineWidth=1;
    c.beginPath();c.moveTo(x,p.t);c.lineTo(x,h-p.b);c.stroke();
    var my=Math.max(p.t,Math.min(h-p.b,st.y||p.t)),priceAtY=high-(my-p.t)/plotH*range;
    c.beginPath();c.moveTo(p.l,my);c.lineTo(w-p.r,my);c.stroke();c.setLineDash([]);
    c.font='10px Microsoft YaHei';c.textAlign='right';c.textBaseline='middle';
    var priceText=priceAtY.toFixed(2),ptw=c.measureText(priceText).width;
    c.fillStyle='#526680';c.fillRect(w-p.r-ptw-8,my-8,ptw+8,16);c.fillStyle='#fff';c.fillText(priceText,w-p.r-4,my);
    var allRows=klineState.data,startIdx=allRows.length-(klineState.panOffset||0)-rows.length,prev=allRows[startIdx+i-1],prevClose=prev?prev.close:row.open,chg=prevClose?(row.close-prevClose)/prevClose*100:0,up=chg>=0;
    var lines=[String(row.time).slice(0,10),'开 '+row.open.toFixed(2)+'　高 '+row.high.toFixed(2),'低 '+row.low.toFixed(2)+'　收 '+row.close.toFixed(2),'涨跌 '+(up?'+':'')+chg.toFixed(2)+'%','量 '+numberText(row.volume/1000000,2)+' 万手'];
    var bw=Math.max.apply(null,lines.map(function(t){return c.measureText(t).width}))+16,bx=p.l+8,by=p.t+8,bh=lines.length*15+10;
    c.fillStyle='rgba(255,255,255,.94)';c.fillRect(bx,by,bw,bh);c.strokeStyle='#d5e0ef';c.strokeRect(bx+.5,by+.5,bw,bh);
    c.textAlign='left';lines.forEach(function(t,li){c.fillStyle=li===3?(up?CHART_UP_RED:CHART_DOWN_GREEN):'#243957';c.fillText(t,bx+8,by+12+li*15)});
    var vcv=$('#volumeChart');
    if(vcv&&vcv.offsetParent){var vs=chartCtx(vcv),vc=vs.c;vc.strokeStyle='#8b99ad';vc.setLineDash([4,3]);vc.lineWidth=1;vc.beginPath();vc.moveTo(x,0);vc.lineTo(x,vs.h);vc.stroke();vc.setLineDash([])}
  }
  var klineCrossRaf=0;
  $('#priceChart').addEventListener('mousemove',function(event){
    if(klineDrag||!klineState.data.length)return;
    var rect=this.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,rows=visibleKlineRows();if(!rows.length)return;
    var step=(rect.width-48-12)/rows.length,index=Math.max(0,Math.min(rows.length-1,Math.round((x-48)/step-.5)));
    klineState.crosshair={index:index,y:y};
    if(klineCrossRaf)return;
    klineCrossRaf=requestAnimationFrame(function(){klineCrossRaf=0;redrawKlineWithCrosshair()});
  });
  $('#priceChart').addEventListener('mouseleave',function(){
    if(!klineState.crosshair)return;klineState.crosshair=null;priceChart();volumeChart();
  });
```

说明：`chartCtx` 复用 setup 的 transform 但**不清屏**（叠加层画在 priceChart/volumeChart 之后）；信息面板固定左上角，涨跌行随正负红绿；竖线贯穿价格图与成交量图（x 坐标系一致）；前收取 `allRows[startIdx+i-1]`，首柱退化为今开。

- [ ] **Step 3: 静态校验**

```bash
node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "drawKlineCrosshair\|klineState.crosshair" app/static/high-fidelity-demo.js | head -10
```

预期：`SYNTAX_OK`；crosshair 定义/赋值/读取点齐全。

- [ ] **Step 4: Commit**

```bash
git add app/static/high-fidelity-demo.js
git commit -m "feat(charts): K线十字光标与悬浮OHLC详情，价格/成交量双图联动参考线"
```

---

### Task 4: 雷达图顶点数值标注

**Files:**
- Modify: `app/static/qs-charts.js`（`radar()` 函数）

**Interfaces:**
- Consumes: Task 1 的 `QSCharts.radar` 内部结构（`point/area/colors/labels/values/values2/n/r/w/h/c`）
- Produces: 无新接口；`radar()` 行为变化——非零顶点绘制数值文本

- [ ] **Step 1: 在 radar() 的 area 调用行之后追加标注逻辑**

```js
// 旧
    if(values2)area(values2,colors.compare,'rgba(16,162,93,.07)');area(values,colors.primary,'rgba(23,104,239,.11)')
  }
// 新
    if(values2)area(values2,colors.compare,'rgba(16,162,93,.07)');area(values,colors.primary,'rgba(23,104,239,.11)')
    function annotate(vals,color,out){
      c.font='10px Microsoft YaHei';vals.forEach(function(v,i){
        if(!Number.isFinite(v)||v===0)return;
        var rr=out?r*v/100+12:Math.max(10,r*v/100-12),pnt=point(i,rr),a=Math.cos(-Math.PI/2+i*Math.PI*2/n),txt=String(Math.round(v)),tw=c.measureText(txt).width;
        c.textAlign=a>.3?'left':a<-.3?'right':'center';
        var lx=pnt[0];if(c.textAlign==='left')lx=Math.max(6,Math.min(lx,w-6-tw));else if(c.textAlign==='right')lx=Math.min(w-6,Math.max(lx,6+tw));else lx=Math.max(6+tw/2,Math.min(w-6-tw/2,lx));
        var ly=Math.max(10,Math.min(h-10,pnt[1]));
        c.fillStyle=color;c.fillText(txt,lx,ly);
      });
    }
    if(values2)annotate(values2,colors.compare,false);annotate(values,colors.primary,true);
    c.textAlign='center';
  }
```

说明：主系列（蓝）标顶点沿轴外侧 12px，对比系列（绿）标内侧 12px（`Math.max(10,...)` 防小数值翻转）；0/NaN 不标；对齐与钳制规则与标签一致。

- [ ] **Step 2: 静态校验**

```bash
node --check app/static/qs-charts.js && echo SYNTAX_OK
grep -n "annotate" app/static/qs-charts.js
```

预期：`SYNTAX_OK`；annotate 定义 + 两处调用。

- [ ] **Step 3: Commit**

```bash
git add app/static/qs-charts.js
git commit -m "feat(charts): 雷达图顶点数值标注，主/对比系列内外错位防重叠"
```

---

### Task 5: 端到端回归验证（控制器执行）

**Files:**
- 无修改（纯验证任务）

**Interfaces:**
- Consumes: Task 1-4 全部改动
- Produces: 验证结论

- [ ] **Step 1: 静态检查汇总**

```bash
cd "F:\tools\3.3 realyy\3.4html展示\3.4html展示\qingtianshu-main\qingtianshu-main"
node --check app/static/qs-charts.js && node --check app/static/high-fidelity-demo.js && echo SYNTAX_OK
grep -n "function setup(\|function line(\|function radar(\|pendingDraw\|slice(-count)" app/static/high-fidelity-demo.js || echo MAIN_CLEAN
grep -c "QSCharts" app/static/high-fidelity-demo.js
grep -n "qs-charts.js" app/static/high-fidelity-demo.html
```

预期：`SYNTAX_OK`、`MAIN_CLEAN`、QSCharts 引用 ≥2（别名两行）、HTML 标签在 demo 之前。

- [ ] **Step 2: CDP 浏览器验证（复用第一轮 harness）**

Python 3.12 启动 uvicorn（`.venv` 已坏，勿用）：`"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m uvicorn app.main:app --port 8000`。编写 `verify-cdp3.mjs`（`Input.dispatchMouseEvent` 合成事件）：

| 检查 | 动作 | 预期 |
|---|---|---|
| 十字光标出现 | mouseMoved 至价格图中心 | 截图见十字线+左上信息面板+右侧价格标签 |
| 十字光标消失 | mouseMoved 至图外 | 截图还原无叠加 |
| 拖拽平移 | 价格图按下→右移 200px→松开 | `#klineStatus` 含「历史视图」、X 轴首日日期前移、截图 |
| 双击复位 | dblclick 价格图 | 「历史视图」消失、回最新数据 |
| 缩放兼容 | 拖走后点「＋」 | 无报错、panOffset 被钳制 |
| 雷达数值标注 | 评分页五维雷达 + 复盘页市场雷达截图 | 顶点旁见数值、无溢出裁切 |
| 第一轮回归 | 缩到 12 根 | MA20 紫线仍贯穿全宽 |
| 六页 Console | 逐页切换 | 零 error 级日志 |

- [ ] **Step 3: 汇报验证结论（无 commit）**
