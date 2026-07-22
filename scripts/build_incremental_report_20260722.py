from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "report_assets" / "incremental_20260722"
OUTPUT = ROOT / "清数智算MVP增量工作与产品质量复盘报告-20260722.docx"

FONT = "PingFang SC"
NAVY = "17365D"
BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
INK = "243447"
MUTED = "64748B"
LIGHT = "F4F7FB"
PALE_BLUE = "EAF2F8"
PALE_GREEN = "EAF7F2"
PALE_GOLD = "FFF7E6"
PALE_RED = "FCEDEE"
BORDER = "D8E2EC"
WHITE = "FFFFFF"
GREEN = "26866A"
GOLD = "8A6717"
RED = "A64B54"

USABLE_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_TOP_BOTTOM_DXA = 80
CELL_SIDE_DXA = 120


def set_run_font(
    run,
    *,
    size: float | None = None,
    color: str | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), FONT)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), FONT)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_style_font(style, *, size: float, color: str, bold: bool = False) -> None:
    style.font.name = FONT
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), FONT)
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), FONT)
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (
        ("top", CELL_TOP_BOTTOM_DXA),
        ("bottom", CELL_TOP_BOTTOM_DXA),
        ("start", CELL_SIDE_DXA),
        ("end", CELL_SIDE_DXA),
    ):
        node = tc_mar.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color: str = BORDER, size: int = 6) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def set_table_geometry(table, widths: list[int], *, indent: int = TABLE_INDENT_DXA) -> None:
    if sum(widths) != USABLE_DXA:
        raise ValueError(f"table widths must total {USABLE_DXA}, got {sum(widths)}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(USABLE_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent))
    tbl_ind.set(qn("w:type"), "dxa")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            width = widths[min(index, len(widths) - 1)]
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    set_style_font(normal, size=11, color=INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    for name, size, color, before, after in (
        ("Heading 1", 16, BLUE, 16, 8),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, DARK_BLUE, 8, 4),
    ):
        style = doc.styles[name]
        set_style_font(style, size=size, color=color, bold=True)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    caption = doc.styles["Caption"]
    set_style_font(caption, size=9, color=MUTED)
    caption.font.italic = True
    caption.paragraph_format.space_before = Pt(4)
    caption.paragraph_format.space_after = Pt(8)
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER


def add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    fld_char = OxmlElement("w:fldChar")
    fld_char.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char, instr, separate, text, end])
    set_run_font(run, size=9, color=MUTED)


def configure_section(section) -> None:
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.82)
    section.bottom_margin = Inches(0.78)
    section.left_margin = Inches(0.92)
    section.right_margin = Inches(0.92)
    section.header_distance = Inches(0.42)
    section.footer_distance = Inches(0.42)

    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hp.paragraph_format.space_after = Pt(0)
    run = hp.add_run("清数智算｜MVP 增量工作与产品质量复盘")
    set_run_font(run, size=9, color=MUTED, bold=True)

    footer = section.footer
    footer.is_linked_to_previous = False
    table = footer.add_table(rows=1, cols=2, width=Inches(6.5))
    set_table_geometry(table, [6800, 2560], indent=0)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    left, right = table.rows[0].cells
    for cell in (left, right):
        tc_pr = cell._tc.get_or_add_tcPr()
        borders = tc_pr.find(qn("w:tcBorders"))
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            tc_pr.append(borders)
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            node = OxmlElement(f"w:{edge}")
            node.set(qn("w:val"), "nil")
            borders.append(node)
    lp = left.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    lr = lp.add_run("内部产品与工程状态说明｜不构成投资建议")
    set_run_font(lr, size=8.5, color=MUTED)
    rp = right.paragraphs[0]
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rr = rp.add_run("第 ")
    set_run_font(rr, size=8.5, color=MUTED)
    add_page_number(rp)
    rr2 = rp.add_run(" 页")
    set_run_font(rr2, size=8.5, color=MUTED)


def add_title_block(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(28)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run("清数智算金融研究 Agent MVP")
    set_run_font(r, size=13, color=BLUE, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(7)
    r = p.add_run("增量工作与产品质量复盘报告")
    set_run_font(r, size=28, color=NAVY, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run("基于 2026-07-22 12:49 版功能与系统架构报告的后续迭代")
    set_run_font(r, size=13, color=MUTED)

    metadata = [
        ("报告基线", "《清数智算MVP功能与系统架构报告-20260722》"),
        ("统计范围", "2026-07-22 12:49 至 18:42（Asia/Shanghai）"),
        ("验证方式", "真实浏览器操作、Hermes Run、SQLite 记录、自动化回归"),
        ("报告定位", "增量总结、质量复盘与下一阶段收敛建议"),
    ]
    table = doc.add_table(rows=len(metadata), cols=2)
    set_table_geometry(table, [1900, 7460])
    set_table_borders(table, color=BORDER, size=4)
    for row, (label, value) in zip(table.rows, metadata, strict=True):
        set_cell_shading(row.cells[0], PALE_BLUE)
        p0 = row.cells[0].paragraphs[0]
        r0 = p0.add_run(label)
        set_run_font(r0, size=9.5, color=DARK_BLUE, bold=True)
        p1 = row.cells[1].paragraphs[0]
        r1 = p1.add_run(value)
        set_run_font(r1, size=9.5, color=INK)

    doc.add_paragraph()
    add_callout(
        doc,
        "核心结论",
        "这段时间最重要的进展不是继续堆功能，而是把“回答为什么不可信、为什么不完整、为什么难读”转成可复现、可测试、可追溯的工程问题。后端研究能力与证据链明显增强，但产品仍处于“技术能力强于用户感知”的阶段。",
        fill=PALE_GOLD,
        accent=GOLD,
    )

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("2026-07-22｜内部评审版")
    set_run_font(r, size=10, color=MUTED, bold=True)


def add_callout(
    doc: Document,
    label: str,
    body: str,
    *,
    fill: str = PALE_BLUE,
    accent: str = BLUE,
) -> None:
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [USABLE_DXA])
    set_table_borders(table, color=accent, size=8)
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(label)
    set_run_font(r, size=10, color=accent, bold=True)
    p = cell.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.18
    r = p.add_run(body)
    set_run_font(r, size=10.5, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_bullet(doc: Document, text: str, *, color: str = INK) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.5)
    p.paragraph_format.first_line_indent = Inches(-0.25)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.167
    r = p.add_run(text)
    set_run_font(r, size=10.5, color=color)


def add_numbered(doc: Document, number: int, title: str, body: str) -> None:
    table = doc.add_table(rows=1, cols=2)
    set_table_geometry(table, [820, 8540])
    set_table_borders(table, color=WHITE, size=0)
    left, right = table.rows[0].cells
    set_cell_shading(left, PALE_BLUE)
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"{number:02d}")
    set_run_font(r, size=14, color=BLUE, bold=True)
    p = right.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(title)
    set_run_font(r, size=11.5, color=NAVY, bold=True)
    p = right.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(body)
    set_run_font(r, size=10.2, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_metric_strip(doc: Document) -> None:
    values = [
        ("336", "自动化测试", BLUE),
        ("53/54", "数据健康", GREEN),
        ("0", "严重数据错误", GREEN),
        ("4", "本轮真实页面截图", GOLD),
    ]
    table = doc.add_table(rows=1, cols=4)
    set_table_geometry(table, [2340, 2340, 2340, 2340])
    set_table_borders(table, color=BORDER, size=5)
    for cell, (value, label, color) in zip(table.rows[0].cells, values, strict=True):
        set_cell_shading(cell, LIGHT)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(value)
        set_run_font(r, size=20, color=color, bold=True)
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(label)
        set_run_font(r, size=9, color=MUTED, bold=True)


def add_status_matrix(doc: Document) -> None:
    rows = [
        ("已经明显改善", "数据时间口径、行业证据、回答流式体验、可见引用、研究空间层级"),
        ("仍然效果一般", "标准问答偶尔过度展开；证据很多但重点不够聚焦；1280px 下聊天区域仍偏拥挤"),
        ("尚未完成", "生产级账户与数据库、授权行情 SLA、独立任务队列、真实操作流水与交易复盘"),
    ]
    table = doc.add_table(rows=1, cols=2)
    set_table_geometry(table, [2200, 7160])
    set_table_borders(table, color=BORDER, size=5)
    for index, (title, detail) in enumerate(rows):
        row = table.rows[0] if index == 0 else table.add_row()
        set_table_geometry(table, [2200, 7160])
        colors = (PALE_GREEN, PALE_GOLD, PALE_RED)
        accents = (GREEN, GOLD, RED)
        set_cell_shading(row.cells[0], colors[index])
        p = row.cells[0].paragraphs[0]
        r = p.add_run(title)
        set_run_font(r, size=10, color=accents[index], bold=True)
        p = row.cells[1].paragraphs[0]
        r = p.add_run(detail)
        set_run_font(r, size=10, color=INK)


def add_figure(doc: Document, path: Path, caption: str, *, width: float = 6.35) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(3)
    p.add_run().add_picture(str(path), width=Inches(width))
    cap = doc.add_paragraph(caption, style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


def add_page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def add_section_title(doc: Document, title: str, subtitle: str | None = None) -> None:
    doc.add_heading(title, level=1)
    if subtitle:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
        r = p.add_run(subtitle)
        set_run_font(r, size=10.5, color=MUTED)


def build() -> Path:
    doc = Document()
    configure_styles(doc)
    configure_section(doc.sections[0])
    add_title_block(doc)

    add_page_break(doc)
    add_section_title(doc, "一、阶段结论", "从功能数量转向真实可用性、针对性与可信度")
    add_metric_strip(doc)
    doc.add_paragraph()
    add_callout(
        doc,
        "本阶段判断",
        "后端已经从“能返回答案”推进到“能区分时间、证据层级和不能确认项”；前端已经从功能入口集合推进到可持续研究空间。但真实测试仍表明：模型回答有时会引用过多无关信息，页面也还没有把最重要的结论和下一步压缩到足够清楚。",
        fill=PALE_BLUE,
        accent=BLUE,
    )
    add_status_matrix(doc)
    doc.add_heading("为什么用户仍会觉得效果一般", level=2)
    add_bullet(doc, "功能完成度不等于用户感知。用户首先感受到的是回答是否切题、页面是否好读、证据是否能一眼核对。")
    add_bullet(doc, "系统已有大量分析模块，但标准问答仍可能把市场广度、资金流、新闻线索一起展开，稀释最关键结论。")
    add_bullet(doc, "守卫已经能拦截很多错误，但频繁依赖事后删行说明约束仍需要进一步前移到证据裁剪和回答契约。")

    add_page_break(doc)
    add_section_title(doc, "二、0722 报告之后完成的增量工作", "以下内容以 12:49 交付版本为基线，不重复旧报告已经覆盖的能力")
    timeline = [
        ("对齐同事最新 PRD 与视觉稿", "重新阅读技术规范、完整 PRD 和今日观察、AI研究、我的关注、股票复盘等页面，明确优势在信息层级和任务路径，而不是功能数量。"),
        ("修正个股“今天”与历史日线的时间错位", "新增 current_quote 优先级，严格区分收盘后报价、盘中报价与最近完整日 K；历史技术指标不再冒充今日行情。"),
        ("补齐同日精确行业证据", "接入中证官方行业指数、样本名单与权重，生成成分上涨/下跌家数和静态贡献估算，避免用宽泛电子板块替代通信设备。"),
        ("升级 Hermes 实时输出与回答守卫", "采用累计流式守卫，先显示安全片段，再用最终完整守卫原位替换；保存首片段、首个安全可见片段和完整耗时。"),
        ("建立用户可见证据链", "回答返回并持久化行情、日线、财务、利润现金流、公告、新闻和资料库引用；历史对话恢复后仍能展开本轮来源。"),
        ("重排股票研究空间", "首屏改为价格与估值、K线、当前研究摘要、用户判断、重要变化和待处理任务；复杂证据通过点击阅读器渐进展开。"),
        ("真实测试并修复回答截断", "发现守卫把“利润下降 46.58%，目前没有新的公告”中的 46.58 误识别为日期，删除了整段结论；现已限制为合法月日组合并新增回归测试。"),
    ]
    for index, (title, body) in enumerate(timeline, 1):
        add_numbered(doc, index, title, body)

    add_page_break(doc)
    add_section_title(doc, "三、后端金融数据与分析逻辑的增强", "把价格、行业、财务与事件放到同一交易日和同一证据层级中")
    add_figure(doc, ROOT / "report_assets" / "answer-flow.png", "图 1｜当前回答主链：确定性数据与资料先组织，Hermes 负责解释，最终再经过证据守卫", width=6.15)
    doc.add_heading("1. 时间口径成为一等数据", level=2)
    add_bullet(doc, "当前报价与完整日线分别保存时间锚点；“今天、当前、盘中、最新”必须优先使用更新报价。")
    add_bullet(doc, "目标交易日用于对齐个股、代表性指数、全市场广度、板块与行业指数；跨日证据不能解释当日涨跌。")
    doc.add_heading("2. 行业归因从宽泛标签升级为可审计证据", level=2)
    add_bullet(doc, "通信设备指数 931160 使用中证官方定义、样本和权重。目标日覆盖 50/50，只股票中 16 只上涨、34 只下跌。")
    add_bullet(doc, "中兴通讯官方权重 3.741%，静态估算贡献约 -0.2359 个百分点；同时保留估算合计与官方指数收益的对账差，不包装成官方逐日归因。")
    doc.add_heading("3. 用户可见证据与长期资料同步", level=2)
    add_bullet(doc, "本轮结构化证据包含最新报价、最近完整日线、财报质量、利润现金流拆解、公司公告和高质量新闻线索。")
    add_bullet(doc, "证据不仅返回网页，也写入历史消息 metadata；用户刷新、切换历史对话后仍可展开。")

    add_page_break(doc)
    add_section_title(doc, "四、首页：从行情罗列到“今日关键事实”", "当前首页先告诉用户今天最值得看什么，再向下展开市场全景")
    add_figure(doc, ASSETS / "01_latest_home.png", "图 2｜最新今日观察页：五市场行情、交易状态、当日 K 线和 A 股全景", width=6.42)
    add_bullet(doc, "五市场卡片按开盘状态排序，显示中日韩美与伦敦金的最新价、涨跌、数据时点和当日 K 线。")
    add_bullet(doc, "首屏增加“今日关键事实”和三个可操作入口，避免用户先面对大块数据表。")
    add_bullet(doc, "A 股市场全景明确区分指数时点、上一完整交易日广度和成交额口径，不把成交额解释成资金净流入。")

    add_page_break(doc)
    add_section_title(doc, "五、股票研究空间：把资料变成长期研究对象", "同一用户、同一股票持续沉淀判断、变化、证据、任务、对话和报告")
    add_figure(doc, ASSETS / "04_stock_research_space.png", "图 3｜中兴通讯股票研究空间：价格、估值、K 线和研究摘要在首屏汇合", width=6.42)
    add_bullet(doc, "首屏不再直接铺开全部财务和新闻，而是先给当前判断、盈利与现金流状态、关键变化和待处理任务。")
    add_bullet(doc, "价格、盈利、现金流和证据四个摘要均可点击，打开完整数据时间、机械影响、反方证据和复核事项。")
    add_bullet(doc, "用户关注理由与系统确定性观察分开呈现，避免把用户假设写成已经验证的公司事实。")

    add_page_break(doc)
    add_section_title(doc, "六、AI研究：实时回答、历史对话与可见证据", "研究对话已经能持续保存，但回答焦点仍需进一步收紧")
    add_figure(doc, ASSETS / "02_latest_agent.png", "图 4｜AI研究页：历史对话、当前标的 K 线、技术状态和连续追问", width=6.38)
    add_figure(doc, ASSETS / "03_evidence_chain.png", "图 5｜回答下方可展开本轮证据与引用；结构化证据可进入本地阅读器", width=6.38)
    add_bullet(doc, "Enter 直接发送、Shift+Enter 换行；对话按用户持久化，可创建、恢复、重命名和归档多个研究会话。")
    add_bullet(doc, "Hermes 根据当前问题、确定性证据、资料库和 Skills 生成回答，而不是复用固定模板。")
    add_bullet(doc, "最新中兴通讯问题能够区分单日价格修复、历史趋势偏弱、财报盈利承压、公告支持事件与不能确认的经营因果。")

    add_page_break(doc)
    add_section_title(doc, "七、一次真实测试如何改变了产品", "回答“成功返回”不等于回答完整，必须检查用户实际看到的最后一段")
    add_callout(
        doc,
        "测试问题",
        "请用最新证据重新判断：中兴通讯今天上涨是否说明基本面反转？",
        fill=PALE_BLUE,
        accent=BLUE,
    )
    doc.add_heading("发现的问题", level=2)
    add_bullet(doc, "Hermes 原始回答完整，最后明确说明单日上涨不能替代利润、毛利率和经营现金流证据。")
    add_bullet(doc, "守卫把“46.58%”误识别为靠近“公告”的月日格式，删除整行，页面只剩“不能确认的部分”空标题。")
    doc.add_heading("修复方式", level=2)
    add_bullet(doc, "日期一致性检查只接受 1—12 月、1—31 日的合法组合；46.58 不再被当成日期。")
    add_bullet(doc, "新增聚焦回归测试，验证百分比靠近“公告/披露”时不会触发财报公告日期冲突。")
    add_bullet(doc, "回答渲染新增首句结论、章节标题和关键边界样式，让用户能快速扫读。")
    doc.add_heading("复测结果", level=2)
    add_bullet(doc, "同一问题再次通过 Enter 发送，Hermes 完整返回当日价格、财务反证、支持事件和最关键不能确认项。")
    add_bullet(doc, "本轮回答显示 10—11 项来源，刷新后历史消息和引用仍保留；全量测试增加至 336 项并全部通过。")
    add_callout(
        doc,
        "质量启示",
        "金融 Agent 的关键不是“模型能说多少”，而是每个时间、数字、因果和来源都能被验证；同时，守卫不能为了安全把有效结论删成残缺回答。",
        fill=PALE_GOLD,
        accent=GOLD,
    )

    add_page_break(doc)
    add_section_title(doc, "八、目前仍然存在的问题", "这是新报告最重要的诚实边界")
    problems = [
        ("回答焦点仍不够稳定", "即使用户只问“是否基本面反转”，标准回答有时仍会带入资金流、换手率和较多媒体线索。需要从 Prompt 提醒升级为问题级证据裁剪。"),
        ("页面信息密度仍偏高", "1280px 桌面宽度下，历史对话、正文和右侧金融侧栏同时存在，中心阅读区域偏窄；证据超过 10 项时展开成本较高。"),
        ("守卫修复频率仍然偏高", "安全网必要，但高频事后删行会损害完整性。应把常见冲突前移到数据契约、Prompt 和针对性测试。"),
        ("任务闭环尚未完整", "研究任务可以查看依据，但忽略、完成、等待数据、重新打开和写回研究档案的状态机还不完整。"),
        ("数据源与生产架构仍是 MVP", "免费公开数据没有 SLA；当前仍是 SQLite、单机后台线程和匿名个人会话，未完成 PostgreSQL/TimescaleDB、Redis、独立任务队列和正式账户体系。"),
        ("不应把当前版本包装成成熟商业产品", "技术原型已能持续运行并支持内部验证，但稳定性、授权数据、运营监控和真实用户留存尚未证明。"),
    ]
    for index, (title, body) in enumerate(problems, 1):
        add_numbered(doc, index, title, body)

    add_page_break(doc)
    add_section_title(doc, "九、下一阶段收敛目标", "停止横向堆功能，优先把一个问题回答得更短、更准、更可信")
    priorities = [
        ("P0｜问题级证据裁剪", "为“涨跌原因、基本面反转、财报解读、事件影响、风险”建立独立证据白名单，模型看不到无关资金流和低质量线索。"),
        ("P0｜回答完整性门槛", "最终答案不能以空标题、残缺列表或缺少结论结束；若修复删除核心段落，应重新生成或追加确定性边界。"),
        ("P0｜证据渐进披露", "正文只显示 3—5 项最关键来源，其余进入证据抽屉；右侧侧栏默认展示行情，证据按需切换。"),
        ("P0｜固定真实问题集", "建立至少 30 个散户高频问题，记录切题度、数字正确率、引用完整率、首次可见时间和人工评分，持续回归。"),
        ("P1｜研究任务写回", "完成任务状态机、证据到期提醒和重新打开逻辑，使研究空间真正支持长期使用。"),
        ("P1｜生产化底座", "在授权数据和真实账户需求明确后，再迁移数据库、缓存、任务队列、审计和权限体系。"),
    ]
    for index, (title, body) in enumerate(priorities, 1):
        add_numbered(doc, index, title, body)
    add_callout(
        doc,
        "建议的核心验收句",
        "用户随便问一个市场或个股问题，系统在数秒内给出针对当前问题的结论；每个关键数字都能展开来源；回答刷新后仍保存；没有固定模板、空标题、内部错误信息或无关数据堆砌。",
        fill=PALE_GREEN,
        accent=GREEN,
    )

    add_page_break(doc)
    add_section_title(doc, "十、最新验证结果与最终判断", "本报告生成前重新执行了完整回归和产品页面验收")
    rows = [
        ("自动化测试", "336 passed in 10.39s", "通过"),
        ("Python 静态检查", "ruff check .", "通过"),
        ("前端脚本", "内联 JavaScript 解析检查", "通过"),
        ("服务健康", "status=ok，Hermes enabled", "通过"),
        ("数据健康", "53/54 healthy，1 项同步中，0 项严重错误", "可用"),
        ("浏览器验收", "首页、AI研究、证据展开、股票研究空间", "通过"),
    ]
    table = doc.add_table(rows=1, cols=3)
    set_table_geometry(table, [2100, 5480, 1780])
    set_table_borders(table, color=BORDER, size=5)
    headers = ("检查项", "结果", "状态")
    for cell, header in zip(table.rows[0].cells, headers, strict=True):
        set_cell_shading(cell, "F2F4F7")
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(header)
        set_run_font(r, size=9.5, color=NAVY, bold=True)
    for item, result, status in rows:
        row = table.add_row()
        set_table_geometry(table, [2100, 5480, 1780])
        for index, value in enumerate((item, result, status)):
            p = row.cells[index].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if index == 2 else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(value)
            color = GREEN if index == 2 else INK
            set_run_font(r, size=9.5, color=color, bold=index == 2)
    doc.add_paragraph()
    add_callout(
        doc,
        "最终判断",
        "从 12:49 版本到现在，产品的真实进展集中在“时间正确、证据可见、回答可追溯、研究可持续”。这比继续增加入口更有价值。但用户指出“效果一般”仍然成立：下一阶段必须把标准问答的焦点、首屏信息层级和任务闭环做到稳定，而不是继续用功能数量证明完成度。",
        fill=PALE_BLUE,
        accent=BLUE,
    )

    doc.core_properties.title = "清数智算MVP增量工作与产品质量复盘报告"
    doc.core_properties.subject = "2026-07-22 12:49 之后的产品与工程增量总结"
    doc.core_properties.author = "清数智算产品研发"
    doc.core_properties.keywords = "清数智算, 金融Agent, Hermes, MVP, 产品复盘"
    doc.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
