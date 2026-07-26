# 图表交互增强与模块化设计（第二轮）

- 日期：2026-07-24
- 前置：第一轮正确性修复已完成并终审通过（spec：`2026-07-24-chart-correctness-fixes-design.md`，分支 `fix/chart-correctness` 未合并）
- 范围：`app/static/high-fidelity-demo.js`、`app/static/high-fidelity-demo.html`（仅加一行 script 标签）、新建 `app/static/qs-charts.js`
- 明确不做：不引图表库、不加成交量均线、不做移动端双指缩放、不动后端

## 1. K线十字光标 + 悬浮详情

**现状**：K线无任何 hover 反馈，用户无法读取单根 K 线的 OHLC。

**方案**：
- 新增状态 `klineState.crosshair`（`null` 或 `{index}`，index 为当前可见窗口内的柱下标）。
- `priceChart` 监听 `mousemove`（rAF 节流）/`mouseleave`：按鼠标 x 坐标定位最近柱中心，`clamp` 到 `[0, rows.length-1]`，写入状态后重绘。
- 重绘顺序：先调现有 `priceChart()`/`volumeChart()`，再叠加绘制：
  - 竖直参考线：柱中心，价格图与成交量图各自贯穿（两图 x 对齐）
  - 水平参考线：鼠标 y 对应价格线（仅价格图），右侧边缘标注价格值
  - 左上信息面板：canvas 内绘制半透明底色矩形 + 文本行——日期、开/高/低/收、涨跌幅（红绿色）、成交量
- `mouseleave`：状态置 `null` 并重绘还原。
- 拖拽平移期间（见 §2）不显示十字光标。
- 仅桌面鼠标；触屏不处理。

## 2. K线拖拽平移历史

**现状**：`visibleKlineRows()` 永远右锚定（`slice(-count)`），只能看最新 N 根。

**方案**：
- 视口模型泛化为 `{count, panOffset}`：`count` 即现有 `visibleBars`；新增 `klineState.panOffset`（距右端的偏移柱数，默认 0）。
- `visibleKlineRows()` 改为：
  - `count = min(生效count, data.length)`
  - `end = data.length - panOffset`；`start = max(0, end - count)`
  - 返回 `{rows: data.slice(start, end), start}`（同时返回 start 供 MA 对齐）
- MA 对齐泛化：第一轮实现的 `maOffset = allRows.length - rows.length` 改为 `maOffset = start`（右锚定时 start ≡ allRows.length − rows.length，行为不变；平移后仍正确）。
- 交互：`mousedown` 于价格图记录起点与起始 panOffset；`mousemove`（window 级，rAF 节流）按 `deltaBars = round(dx / step)` 更新 `panOffset = clamp(startPan + deltaBars, 0, data.length - count)`（向右拖 = 看更早 = panOffset 增大）；`mouseup` 结束。
- 复位：切换周期、切换股票、双击、点「重置」→ `panOffset = 0`；缩放（±/滚轮）保留 panOffset 但 clamp 到新上限。
- 状态提示：`panOffset > 0` 时 `#klineStatus` 追加 `· 历史视图（双击复位）`。

## 3. 雷达图顶点数值标注

**方案**（改 `radar()`，两个实例共用）：
- `area()` 绘制后，对每个顶点沿轴方向外侧 12px 标注数值（10px，系列色）；`values2`（行业中位）标注在顶点沿轴**内侧** 12px，避免两系列文字重叠。**例外（第二轮终审修订）**：主系列值接近满分致外侧标注进入轴标签环（`r*v/100+12 > r+9`，约 v≳96）时，该点回退为沿轴内侧 12px 标注（`Math.max(10,...)` 防翻转），避免与轴标签重叠。
- 值为 0（无数据）不标注。
- 水平对齐与钳制复用第一轮的角度规则（cos>0.3 左对齐 / <-0.3 右对齐 / 否则居中；x∈[6,w-6]，y∈[10,h-10]）。

## 4. 图表模块抽离 `qs-charts.js`

**方案**：
- 新建 `app/static/qs-charts.js`：IIFE 挂 `window.QSCharts = {colors, setup, line, radar}`：
  - `colors`：`{up:'#f3262d', down:'#079a56', flat:'#bcc3ce', primary:'#1768ef', compare:'#10a25d'}`（第一轮 5 常量原值迁移）
  - `setup(canvas)`、`line(canvas,points,color,fill)`、`radar(canvas)` 原样迁移（radar 含 §3 增强）
- 主文件删除本地定义；为控制 diff，顶部保留一行别名：`var CHART_UP_RED=QSCharts.colors.up, CHART_DOWN_GREEN=..., CHART_FLAT_GRAY=..., CHART_PRIMARY_BLUE=..., CHART_COMPARE_GREEN=...;`，既有 10 处引用不动；`setup/line/radar` 调用点改为 `QSCharts.*`。
- HTML：`<script src="/static/qs-charts.js" defer></script>` 加在 demo 脚本**之前**（defer 保序，demo IIFE 执行时 QSCharts 已就绪）。

## 5. pendingDraw 清理（第一轮终审 Minor 项）

- `topMetricComparisonState.pendingDraw` 为 write-only（只写不读）。删除：state 定义中的字段、`drawTopMetricComparison` 中的 `pendingDraw=true`/`=false` 两处赋值；隐藏画布时改为直接 `return`（重绘由既有 rAF/ResizeObserver/setTimeout 路径覆盖）。

## 错误处理

- 十字光标：无数据/可见行空 → 不响应；index 越界一律 clamp。
- 拖拽：数据 < count → `panOffset` 恒 0；拖拽中切换周期/股票 → 先复位再加载。
- 雷达标注：值非法（NaN）→ 不标注。
- 模块抽离：`QSCharts` 未加载（标签顺序错）→ demo 脚本首行即报错，属部署错误，不做静默兜底。

## 验证方式

1. `node --check` 两个 JS 文件通过。
2. CDP 无头浏览器（复用第一轮 harness，`verify-cdp*.mjs` + Python 3.12 起 uvicorn）：
   - 合成 `mousemove` 至价格图 → 截图确认十字线 + 信息面板出现；`mouseleave` 后消失
   - 合成鼠标拖拽 → X 轴日期前移 + `#klineStatus` 显示「历史视图」；双击复位
   - 两个雷达截图确认顶点数值标注、无溢出
   - 六页切换 Console 零报错
3. 第一轮回归用例重跑（12 根缩放 MA20 贯穿、雷达标签无裁切、grep 残留检查）。

## 实施约束

- 保持 ES5 风格（`var`、函数声明、逗号链）；单文件函数拆分与现有一致。
- 计划阶段如需调整实现细节，以本 spec 的交互与视觉行为为准。
