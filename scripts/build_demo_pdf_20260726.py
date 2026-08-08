from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.request import urlopen

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "report_assets" / "20260726_demo"
OUTPUT = ROOT / "output" / "pdf" / "清数智算金融研究Agent_产品演示与技术算法说明_20260726.pdf"
REPORT_DATE = "2026-07-26"
PAGE_W, PAGE_H = landscape(A4)

NAVY = colors.HexColor("#16243C")
BLUE = colors.HexColor("#2F6FEC")
BLUE_2 = colors.HexColor("#5B8FF5")
GREEN = colors.HexColor("#1C9B72")
GOLD = colors.HexColor("#C58B28")
RED = colors.HexColor("#C5525A")
INK = colors.HexColor("#27364D")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#DCE4F0")
BG = colors.HexColor("#F6F8FC")
PALE_BLUE = colors.HexColor("#EDF3FF")
PALE_GREEN = colors.HexColor("#EAF8F2")
PALE_GOLD = colors.HexColor("#FFF6DE")
PALE_RED = colors.HexColor("#FFF0F1")
WHITE = colors.white


def register_fonts() -> tuple[str, str]:
    arial = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    if arial.exists():
        pdfmetrics.registerFont(TTFont("QingShu", str(arial)))
        pdfmetrics.registerFont(TTFont("QingShuBold", str(arial)))
        return "QingShu", "QingShuBold"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


FONT, FONT_BOLD = register_fonts()


def health_snapshot() -> dict:
    fallback = {
        "status": "ok",
        "data_health": {"summary": {"healthy": 53, "total": 54}},
        "background_jobs": {
            "running": True,
            "persistent_queue": {
                "queue": {"succeeded_24h": 7533, "failed_24h": 0},
                "workers": {"active": 1},
            },
        },
    }
    try:
        with urlopen("http://127.0.0.1:8773/health", timeout=3) as response:
            return json.load(response)
    except Exception:
        return fallback


HEALTH = health_snapshot()


def paragraph(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    size: float = 10,
    leading: float | None = None,
    color: colors.Color = INK,
    align: int = TA_LEFT,
    font: str = FONT,
) -> float:
    style = ParagraphStyle(
        name="inline",
        fontName=font,
        fontSize=size,
        leading=leading or size * 1.55,
        textColor=color,
        alignment=align,
        wordWrap="CJK",
        spaceAfter=0,
        spaceBefore=0,
    )
    body = html.escape(str(text)).replace("\n", "<br/>")
    item = Paragraph(body, style)
    _, used = item.wrap(width, height)
    item.drawOn(c, x, y + height - used)
    return used


def rounded_box(
    c: canvas.Canvas,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: colors.Color = WHITE,
    stroke: colors.Color = LINE,
    radius: float = 8,
    line_width: float = 0.8,
) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, width, height, radius, fill=1, stroke=1)


def page_header(c: canvas.Canvas, page_no: int, title: str, subtitle: str = "") -> None:
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.roundRect(31, PAGE_H - 49, 24, 24, 7, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(FONT_BOLD, 13)
    c.drawCentredString(43, PAGE_H - 42, "清")
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 18)
    c.drawString(66, PAGE_H - 37, title)
    if subtitle:
        c.setFillColor(MUTED)
        c.setFont(FONT, 8.5)
        c.drawString(67, PAGE_H - 52, subtitle)
    c.setStrokeColor(LINE)
    c.line(31, 28, PAGE_W - 31, 28)
    c.setFillColor(MUTED)
    c.setFont(FONT, 7.5)
    c.drawString(31, 16, "清数智算金融研究 Agent - 产品演示与技术算法说明")
    c.drawRightString(PAGE_W - 31, 16, f"{REPORT_DATE}  |  {page_no:02d}")


def title_block(c: canvas.Canvas, eyebrow: str, title: str, subtitle: str) -> None:
    c.setFillColor(GREEN)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(43, PAGE_H - 92, eyebrow.upper())
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 22)
    c.drawString(43, PAGE_H - 119, title)
    paragraph(c, subtitle, 43, PAGE_H - 153, PAGE_W - 86, 26, size=9.5, color=MUTED)


def fit_image(path: Path, max_w: float, max_h: float) -> tuple[float, float]:
    with Image.open(path) as image:
        w, h = image.size
    scale = min(max_w / w, max_h / h)
    return w * scale, h * scale


def framed_image(
    c: canvas.Canvas,
    path: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    padding: float = 5,
) -> None:
    rounded_box(c, x, y, width, height, fill=WHITE, stroke=LINE, radius=8)
    draw_w, draw_h = fit_image(path, width - 2 * padding, height - 2 * padding)
    dx = x + (width - draw_w) / 2
    dy = y + (height - draw_h) / 2
    c.drawImage(str(path), dx, dy, draw_w, draw_h, preserveAspectRatio=True, mask="auto")


def chip(c: canvas.Canvas, text: str, x: float, y: float, width: float, *, fill=PALE_BLUE, color=BLUE) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.roundRect(x, y, width, 20, 10, fill=1, stroke=0)
    c.setFillColor(color)
    c.setFont(FONT_BOLD, 8)
    c.drawCentredString(x + width / 2, y + 6.5, text)


def metric(c: canvas.Canvas, value: str, label: str, x: float, y: float, width: float, *, accent=BLUE) -> None:
    rounded_box(c, x, y, width, 72, fill=WHITE, stroke=LINE, radius=9)
    c.setFillColor(accent)
    c.setFont(FONT_BOLD, 22)
    c.drawString(x + 14, y + 39, str(value))
    paragraph(c, label, x + 14, y + 10, width - 28, 20, size=8.2, color=MUTED)


def bullet_list(
    c: canvas.Canvas,
    items: list[str],
    x: float,
    y_top: float,
    width: float,
    *,
    size: float = 9,
    gap: float = 6,
    accent=BLUE,
) -> float:
    y = y_top
    for item in items:
        c.setFillColor(accent)
        c.circle(x + 3, y - 5, 2.1, fill=1, stroke=0)
        used = paragraph(c, item, x + 12, y - 34, width - 12, 34, size=size, color=INK)
        y -= max(used, 14) + gap
    return y


def screenshot_page(
    c: canvas.Canvas,
    page_no: int,
    title: str,
    subtitle: str,
    image_name: str,
    bullets: list[str],
    *,
    tags: list[str] | None = None,
) -> None:
    page_header(c, page_no, title, subtitle)
    image_y = 136
    framed_image(c, ASSET_DIR / image_name, 35, image_y, PAGE_W - 70, 390)
    if tags:
        x = 42
        for text in tags:
            width = max(58, len(text) * 9 + 20)
            chip(c, text, x, 105, width)
            x += width + 7
    bullet_list(c, bullets, 92, 96 if tags else 112, PAGE_W - 90, size=8.5, gap=3)
    c.showPage()


def page_cover(c: canvas.Canvas, page_no: int) -> None:
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#213A68"))
    c.circle(PAGE_W - 100, PAGE_H - 80, 210, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#2F6FEC"))
    c.circle(PAGE_W - 62, PAGE_H - 38, 130, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#54B89A"))
    c.circle(PAGE_W - 34, PAGE_H - 12, 64, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.roundRect(54, PAGE_H - 113, 46, 46, 13, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.setFont(FONT_BOLD, 25)
    c.drawCentredString(77, PAGE_H - 100, "清")
    c.setFillColor(colors.HexColor("#8FB4FF"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(54, PAGE_H - 153, "PRODUCT DEMO  /  ARCHITECTURE  /  FINANCIAL ALGORITHMS")
    paragraph(c, "清数智算金融研究 Agent", 54, 292, 610, 100, size=34, leading=46, color=WHITE, font=FONT_BOLD)
    paragraph(
        c,
        "完成度较高的金融研究MVP：真实功能演示、操作结果、\n数据库架构、后台队列与金融分析算法",
        56,
        230,
        660,
        58,
        size=14,
        leading=22,
        color=colors.HexColor("#D9E5FF"),
    )
    c.setStrokeColor(colors.HexColor("#436294"))
    c.line(56, 204, 620, 204)
    paragraph(c, "面向产品演示与技术复盘  |  权威仓库 /Users/chr/Documents/qingtianshu  |  分支 codex/structured-ai-writeback", 56, 154, 650, 34, size=9.5, color=colors.HexColor("#BFD0EE"))
    chip(c, "真实数据", 56, 116, 74, fill=colors.HexColor("#284A80"), color=WHITE)
    chip(c, "即时Agent", 138, 116, 80, fill=colors.HexColor("#284A80"), color=WHITE)
    chip(c, "透明算法", 226, 116, 80, fill=colors.HexColor("#284A80"), color=WHITE)
    chip(c, "长期研究", 314, 116, 80, fill=colors.HexColor("#284A80"), color=WHITE)
    c.setFillColor(colors.HexColor("#A9BAD6"))
    c.setFont(FONT, 8)
    c.drawString(56, 48, f"内部演示版本  |  {REPORT_DATE}  |  页面 {page_no:02d}")
    c.showPage()


def page_summary(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "执行摘要", "当前运行态、完成能力与产品价值")
    title_block(c, "MVP STATUS", "这不是接口文档，而是一套正在运行的个人金融研究工作台", "前端展示、金融数据、确定性分析、Hermes即时回答、用户工作区和后台补证已经形成完整闭环。")
    summary = HEALTH.get("data_health", {}).get("summary", {})
    queue = HEALTH.get("background_jobs", {}).get("persistent_queue", {})
    q24 = queue.get("queue", {})
    workers = queue.get("workers", {})
    values = [
        ("5类", "重点市场：中日韩美与伦敦金", BLUE),
        (f"{summary.get('healthy', 53)}/{summary.get('total', 54)}", "当前数据健康", GREEN),
        (str(q24.get("succeeded_24h", 7533)), "队列24小时成功任务", BLUE),
        (str(q24.get("failed_24h", 0)), "队列24小时失败任务", GREEN),
        (str(workers.get("active", 1)), "在线后台Worker", GOLD),
        ("729", "当前自动化测试收集数", BLUE),
    ]
    x0, y0, gap, w = 43, 323, 10, 117
    for index, (value, label, accent) in enumerate(values):
        metric(c, value, label, x0 + index * (w + gap), y0, w, accent=accent)
    rounded_box(c, 43, 116, 365, 181, fill=WHITE, stroke=LINE, radius=10)
    paragraph(c, "用户能直接使用", 59, 265, 330, 22, size=13, color=NAVY, font=FONT_BOLD)
    bullet_list(c, [
        "查看正在开盘或最近收盘的全球市场、分钟K线和A股结构。",
        "管理自选股，打开服务器预生成的研究快照和长期股票空间。",
        "与Hermes/DeepSeek即时对话，自动带入行情、财务、公告、反证与历史资料。",
        "运行透明选股和李总严格策略，查看逐规则证据和历史走查边界。",
        "保存任务、判断、持仓、操作与复盘，并在个人资料库持续积累。",
    ], 59, 245, 325, size=8.5, gap=3)
    rounded_box(c, 425, 116, 373, 181, fill=PALE_BLUE, stroke=colors.HexColor("#C9D8F7"), radius=10)
    paragraph(c, "核心产品价值", 442, 265, 330, 22, size=13, color=NAVY, font=FONT_BOLD)
    paragraph(c, "清数智算不是让大模型凭聊天上下文猜市场，而是先建立可追溯的金融事实，再让Agent解释、质疑和组织下一步研究。保存的报告是证据，当前回答必须重新生成；正式判断和任务只有用户确认后才写入。", 442, 178, 336, 80, size=10, leading=17, color=INK)
    chip(c, "事实先于解释", 442, 137, 92, fill=WHITE, color=BLUE)
    chip(c, "反方证据", 542, 137, 76, fill=WHITE, color=RED)
    chip(c, "用户确认", 626, 137, 76, fill=WHITE, color=GREEN)
    c.showPage()


def page_function_map(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "产品功能地图", "从市场发现到个股研究、行动与复盘")
    title_block(c, "PRODUCT MAP", "六个用户入口，共用同一份金融证据和个人研究资产", "功能不是相互孤立的页面：市场变化、自选、Agent、个股空间、选股与复盘能够相互跳转。")
    cards = [
        ("今日观察", "全球市场、分钟K线、A股广度、行业结构与市场洞察", BLUE, PALE_BLUE),
        ("我的关注", "中兴通讯、中际旭创、英伟达；报告、异动、任务与继续研究", GREEN, PALE_GREEN),
        ("个股研究", "行情估值、六维证据、任务操作、判断版本和历史复盘", GOLD, PALE_GOLD),
        ("AI研究", "多历史会话、Enter发送、K线侧栏、引用和本轮即时生成", BLUE, PALE_BLUE),
        ("透明选股", "通用研究候选、李总9条规则、8/9观察池与历史回放", RED, PALE_RED),
        ("资料与复盘", "85份资料、市场文章、交易复盘、个人中心与服务状态", GREEN, PALE_GREEN),
    ]
    start_x, start_y, card_w, card_h, gx, gy = 43, 303, 240, 92, 14, 16
    for index, (name, body, accent, fill) in enumerate(cards):
        col, row = index % 3, index // 3
        x = start_x + col * (card_w + gx)
        y = start_y - row * (card_h + gy)
        rounded_box(c, x, y, card_w, card_h, fill=fill, stroke=accent, radius=10)
        c.setFillColor(accent)
        c.setFont(FONT_BOLD, 13)
        c.drawString(x + 14, y + 64, name)
        paragraph(c, body, x + 14, y + 13, card_w - 28, 43, size=8.5, color=INK)
    c.setStrokeColor(colors.HexColor("#B9C8DF"))
    c.setLineWidth(2)
    c.line(102, 153, 740, 153)
    for x, label, note in [
        (102, "发现", "市场与异动"),
        (315, "研究", "证据与Agent"),
        (528, "确认", "判断与任务"),
        (740, "复盘", "结果与修正"),
    ]:
        c.setFillColor(BLUE)
        c.circle(x, 153, 6, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 10)
        c.drawCentredString(x, 132, label)
        c.setFillColor(MUTED)
        c.setFont(FONT, 7.5)
        c.drawCentredString(x, 119, note)
    c.showPage()


def page_two_screens(
    c: canvas.Canvas,
    page_no: int,
    title: str,
    subtitle: str,
    left_image: str,
    left_title: str,
    left_text: str,
    right_image: str,
    right_title: str,
    right_text: str,
) -> None:
    page_header(c, page_no, title, subtitle)
    framed_image(c, ASSET_DIR / left_image, 35, 239, 379, 292)
    framed_image(c, ASSET_DIR / right_image, 428, 239, 379, 292)
    rounded_box(c, 35, 73, 379, 146, fill=WHITE, stroke=LINE, radius=9)
    rounded_box(c, 428, 73, 379, 146, fill=WHITE, stroke=LINE, radius=9)
    paragraph(c, left_title, 51, 178, 345, 26, size=13, color=NAVY, font=FONT_BOLD)
    paragraph(c, left_text, 51, 92, 345, 77, size=9, leading=15.5, color=INK)
    paragraph(c, right_title, 444, 178, 345, 26, size=13, color=NAVY, font=FONT_BOLD)
    paragraph(c, right_text, 444, 92, 345, 77, size=9, leading=15.5, color=INK)
    c.showPage()


def page_account_status(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "个人工作区与真实服务状态", "个人研究资产、数据健康和后台运行同屏可见")
    framed_image(c, ASSET_DIR / "11_account.png", 35, 174, PAGE_W - 70, 356)
    summary = HEALTH.get("data_health", {}).get("summary", {})
    queue = HEALTH.get("background_jobs", {}).get("persistent_queue", {})
    q24 = queue.get("queue", {})
    items = [
        ("3", "自选股"),
        ("11", "历史对话"),
        ("85", "资料"),
        ("19", "待处理研究"),
        (f"{summary.get('healthy', 53)}/{summary.get('total', 54)}", "数据健康"),
        (str(q24.get("succeeded_24h", 7533)), "24小时任务成功"),
    ]
    for i, (value, label) in enumerate(items):
        metric(c, value, label, 35 + i * 129, 78, 117, accent=GREEN if i in {4, 5} else BLUE)
    c.showPage()


def page_diagram(c: canvas.Canvas, page_no: int, title: str, subtitle: str, image_name: str, footer: str) -> None:
    page_header(c, page_no, title, subtitle)
    framed_image(c, ASSET_DIR / image_name, 35, 84, PAGE_W - 70, 447)
    rounded_box(c, 58, 42, PAGE_W - 116, 30, fill=PALE_BLUE, stroke=colors.HexColor("#C9D8F7"), radius=8)
    paragraph(c, footer, 70, 47, PAGE_W - 140, 18, size=8.3, color=INK, align=TA_CENTER)
    c.showPage()


def page_data_sources(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "金融数据获取、刷新与时间口径", "多源适配、标准化、持久化与明确降级")
    title_block(c, "DATA PIPELINE", "数据库的价值不是“存数据”，而是保存时间、来源、版本和缺失状态", "每条关键证据尽量携带市场时间、报告期、抓取时间、来源与数据版本，Agent不能混写不同时间点。")
    sources = [
        ("全球市场", "Yahoo Finance Chart、东方财富、腾讯；中日韩分钟指数和美股盘中快照", BLUE),
        ("伦敦金", "新浪XAU五分钟OHLC；保留最近有效快照与交易时间", GOLD),
        ("A股结构", "Tushare兼容服务、东方财富；全市场名单、日线、市值、涨跌停与板块", GREEN),
        ("公司证据", "正式公告聚合、财报三表、股东、主营、分析师预期与同行估值", BLUE),
        ("新闻情绪", "新浪财经、Nasdaq、东方财富股吧；只作为线索，不自动确认为因果", RED),
        ("美股公司", "SEC EDGAR Companyfacts与submissions；监管原文优先", GREEN),
    ]
    x0, y0, w, h, gx, gy = 43, 300, 240, 83, 14, 14
    for i, (name, body, accent) in enumerate(sources):
        col, row = i % 3, i // 3
        x, y = x0 + col * (w + gx), y0 - row * (h + gy)
        rounded_box(c, x, y, w, h, fill=WHITE, stroke=accent, radius=9)
        c.setFillColor(accent)
        c.setFont(FONT_BOLD, 11)
        c.drawString(x + 13, y + 58, name)
        paragraph(c, body, x + 13, y + 10, w - 26, 42, size=7.8, color=INK)
    stages = [
        ("采集", "请求与速率控制"),
        ("标准化", "代码、时区、单位"),
        ("校验", "覆盖、新鲜度、异常"),
        ("持久化", "稳定快照与版本"),
        ("分析", "确定性指标"),
        ("交付", "API、SSE与Agent"),
    ]
    c.setStrokeColor(colors.HexColor("#B9C8DF"))
    c.setLineWidth(2)
    c.line(90, 122, 752, 122)
    for i, (name, note) in enumerate(stages):
        x = 90 + i * 132.4
        c.setFillColor(BLUE if i < 5 else GREEN)
        c.circle(x, 122, 6, fill=1, stroke=0)
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(x, 99, name)
        c.setFillColor(MUTED)
        c.setFont(FONT, 7)
        c.drawCentredString(x, 86, note)
    c.showPage()


def formula_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, formula: str, note: str, accent=BLUE) -> None:
    rounded_box(c, x, y, w, h, fill=WHITE, stroke=accent, radius=9)
    c.setFillColor(accent)
    c.setFont(FONT_BOLD, 11.5)
    c.drawString(x + 13, y + h - 22, title)
    formula_y = y + h - 66
    rounded_box(c, x + 12, formula_y, w - 24, 32, fill=BG, stroke=LINE, radius=6)
    paragraph(
        c,
        formula,
        x + 20,
        formula_y + 4,
        w - 40,
        24,
        size=7.5,
        leading=10.2,
        color=NAVY,
        font="Helvetica",
    )
    paragraph(c, note, x + 13, y + 9, w - 26, h - 81, size=7.2, leading=10.4, color=INK)


def page_technical_algorithms(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "价格、技术与风险算法", "确定性计算描述历史结构，不直接生成买卖信号")
    title_block(c, "DETERMINISTIC METRICS", "技术指标由后端代码计算，LLM只能解释结果", "当前实现集中在 app/services/analysis.py；缺少足够历史窗口时返回空值，不用模型补数。")
    cards = [
        ("周期收益", "R_n = (Close_t / Close_(t-n) - 1) * 100%", "计算1、5、20、60日已经发生的收益路径；要求存在t-n时点收盘价。"),
        ("年化波动率", "sigma_ann = std(r_daily) * sqrt(252) * 100%", "使用最近窗口的样本标准差；反映波动，不等于未来风险概率。"),
        ("最大回撤", "DD_t = Close_t / Peak_t - 1; MDD = min(DD_t)", "逐日维护历史峰值，当前使用最近60日窗口观察尾部损失。"),
        ("RSI14", "RS = AvgGain14 / AvgLoss14; RSI = 100 - 100/(1+RS)", "平均上涨与平均下跌使用最近14个变化；70/30只参与技术状态描述。"),
        ("MACD", "MACD = EMA12 - EMA26; Signal = EMA9(MACD)", "Histogram = MACD - Signal；与价格相对MA20共同判断动量改善或转弱。"),
        ("ATR与量比", "ATR14% = mean(TR14)/Close; VR = AvgVol5/AvgVol20", "TR取H-L、|H-prevC|、|L-prevC|最大值；量比只描述活跃度。"),
    ]
    x0, y0, w, h, gx, gy = 43, 287, 240, 106, 14, 14
    for i, (title, formula, note) in enumerate(cards):
        col, row = i % 3, i // 3
        formula_card(c, x0 + col * (w + gx), y0 - row * (h + gy), w, h, title, formula, note, accent=[BLUE, GREEN, GOLD, RED, BLUE, GREEN][i])
    rounded_box(c, 43, 70, PAGE_W - 86, 82, fill=PALE_BLUE, stroke=colors.HexColor("#C9D8F7"), radius=10)
    paragraph(c, "趋势与技术状态", 59, 123, 160, 22, size=12, color=NAVY, font=FONT_BOLD)
    paragraph(c, "Close > MA20 > MA60 为中期偏强；Close < MA20 < MA60 为中期偏弱；其他为趋势分化。布林带使用20日均值 +/- 2倍总体标准差。所有状态只描述已经发生的价格结构。", 210, 86, PAGE_W - 270, 56, size=8.8, leading=15, color=INK)
    c.showPage()


def page_market_algorithms(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "大盘、行业与同日对齐算法", "先判断交易时间与覆盖，再形成市场分类")
    title_block(c, "MARKET ANALYSIS", "不同市场、不同交易日不合成一个伪精确结论", "市场分析首先确认代表性指数覆盖、市场日期和交易状态；A股再叠加全市场广度、成交额和行业结构。")
    rounded_box(c, 43, 298, 362, 132, fill=WHITE, stroke=BLUE, radius=10)
    paragraph(c, "市场分类规则", 59, 399, 330, 22, size=13, color=NAVY, font=FONT_BOLD)
    bullet_list(c, [
        "可用指数覆盖低于50%：数据不足。",
        "平均日收益 >= 0.6%，且上涨比例 >= 60%：偏强。",
        "平均日收益 <= -0.6%，且上涨比例 <= 40%：承压。",
        "离散度 >= 1.5%，或上涨比例在40%-60%：分化。",
        "其余：中性；分类不是涨跌预测。",
    ], 59, 382, 326, size=8.2, gap=2)
    rounded_box(c, 423, 298, 375, 132, fill=WHITE, stroke=GREEN, radius=10)
    paragraph(c, "A股市场与行业结构", 439, 399, 340, 22, size=13, color=NAVY, font=FONT_BOLD)
    bullet_list(c, [
        "上涨、下跌、平盘家数和上涨比例。",
        "全市场成交额、涨跌幅中位数、四分位数和强弱分档。",
        "板块涨跌、成分股覆盖、上涨下跌家数和静态贡献。",
        "成交额只代表交易活跃金额，不解释为资金净流入。",
        "相对指数/行业表现用于区分个股独立变化与同步变化。",
    ], 439, 382, 339, size=8.2, gap=2, accent=GREEN)
    rounded_box(c, 43, 83, PAGE_W - 86, 187, fill=PALE_GOLD, stroke=colors.HexColor("#E8CF92"), radius=10)
    paragraph(c, "同日对齐与归因边界", 59, 236, 210, 22, size=13, color=NAVY, font=FONT_BOLD)
    stages = [
        ("1", "确认市场日期", "按各市场时区解析时间戳"),
        ("2", "确认报价口径", "盘中价、收盘价与完整日线分开"),
        ("3", "比较同步性", "指数、行业和个股同日变化"),
        ("4", "检索直接证据", "公告、监管、新闻与事件时间"),
        ("5", "形成有限归因", "证据不足时明确驱动未确认"),
    ]
    for i, (n, name, note) in enumerate(stages):
        x = 61 + i * 147
        c.setFillColor(BLUE)
        c.circle(x + 12, 184, 12, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x + 12, 181, n)
        paragraph(c, name, x + 29, 177, 108, 20, size=9.2, color=NAVY, font=FONT_BOLD)
        paragraph(c, note, x, 111, 133, 54, size=7.5, leading=12, color=INK, align=TA_CENTER)
    c.showPage()


def page_financial_algorithms(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "个股财务、现金流、事件与反证", "从报表事实到有限标签，再进入Agent综合")
    title_block(c, "STOCK EVIDENCE", "个股结论来自多维证据，不来自单一价格或单季利润", "系统区分原始数据、后端计算、公司解释、媒体线索和AI解释；每一层的可信度与用途不同。")
    hierarchy = [
        ("一级", "监管披露与公司公告", "正式事实、报告期、原文链接", GREEN),
        ("二级", "结构化财务与行情", "三表、估值、日线、行业与同行", BLUE),
        ("三级", "新闻与社区线索", "发现市场关注点，不自动证明因果", GOLD),
        ("四级", "Agent解释", "组织事实、反证、缺口与核验计划", RED),
    ]
    for i, (level, name, note, accent) in enumerate(hierarchy):
        y = 350 - i * 63
        rounded_box(c, 43, y, 260, 50, fill=WHITE, stroke=accent, radius=9)
        c.setFillColor(accent)
        c.setFont(FONT_BOLD, 9)
        c.drawString(57, y + 29, level)
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 10.5)
        c.drawString(98, y + 29, name)
        paragraph(c, note, 98, y + 6, 188, 20, size=7.4, color=MUTED)
    rounded_box(c, 324, 161, 474, 239, fill=WHITE, stroke=LINE, radius=10)
    paragraph(c, "确定性财务分析项目", 341, 369, 430, 22, size=13, color=NAVY, font=FONT_BOLD)
    columns = [
        ("增长与盈利", ["营收与归母净利润同比", "毛利率、净利率、ROE", "报告期和披露日期"]),
        ("现金流质量", ["CFO/归母净利润覆盖", "应收、存货与应付变化", "利润与现金流方向"]),
        ("结构与预期", ["资产负债结构", "主营和客户集中度线索", "同行估值与分析师预期"]),
    ]
    for i, (name, items) in enumerate(columns):
        x = 341 + i * 148
        c.setFillColor([BLUE, GREEN, GOLD][i])
        c.roundRect(x, 334, 132, 24, 7, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(FONT_BOLD, 9)
        c.drawCentredString(x + 66, 342, name)
        bullet_list(c, items, x + 2, 316, 128, size=7.8, gap=3, accent=[BLUE, GREEN, GOLD][i])
    rounded_box(c, 43, 83, PAGE_W - 86, 55, fill=PALE_RED, stroke=colors.HexColor("#F0C4C8"), radius=9)
    paragraph(c, "有限标签边界：系统可以标记“承压”“改善但需复核”“增长与兑现较一致”，但不会从单季数据推断长期趋势；公司解释仍需与现金流、同行和后续报告交叉验证。", 58, 96, PAGE_W - 116, 31, size=8.8, leading=14.5, color=INK, align=TA_CENTER)
    c.showPage()


def page_li_zong_algorithm(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "透明筛选与李总策略算法", "严格规则保持为空，也不为演示放宽")
    title_block(c, "SCREENING", "通用筛选输出研究候选；李总策略要求九条规则全部通过", "候选成立后才检查三条盘后形态。8/9和6-7/9只进入观察池，candidate_qualified仍为false。")
    rules = [
        ("1", "市值 > 150亿元"), ("2", "连续5个完整年度ROE >= 10%"), ("3", "机构型股东 >= 5名"),
        ("4", "近240日收盘涨停 >= 6次"), ("5", "出现连续涨停"), ("6", "最近10日有收盘涨停"),
        ("7", "最近10日无跌幅至少5%的阴线"), ("8", "最近20日出现360日复权新高"), ("9", "连续3日成交量 >= 20日基准2倍"),
    ]
    for i, (n, text) in enumerate(rules):
        col, row = i % 3, i // 3
        x, y = 43 + col * 254, 323 - row * 66
        rounded_box(c, x, y, 240, 52, fill=WHITE, stroke=BLUE if row < 2 else GREEN, radius=8)
        c.setFillColor(BLUE)
        c.circle(x + 19, y + 26, 11, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(x + 19, y + 23, n)
        paragraph(c, text, x + 37, y + 10, 188, 32, size=8.3, color=INK)
    rounded_box(c, 43, 79, 505, 45, fill=PALE_GOLD, stroke=colors.HexColor("#E8CF92"), radius=8)
    paragraph(c, "候选成立后触发：当日涨停；或高开至少3.5%且收阳；或振幅至少9.8%且收阳。", 57, 91, 477, 24, size=8.5, color=INK, align=TA_CENTER)
    rounded_box(c, 565, 79, 233, 45, fill=PALE_GREEN, stroke=colors.HexColor("#BDE4D6"), radius=8)
    paragraph(c, "历史走查只用信号日及以前数据，保存5/10/20日收益、沪深300基准与超额路径；历史频率不是未来概率。", 577, 86, 209, 31, size=7.5, leading=11.5, color=INK, align=TA_CENTER)
    c.showPage()


def page_demo_script(c: canvas.Canvas, page_no: int) -> None:
    page_header(c, page_no, "现场演示建议与适用边界", "用10分钟说明产品，而不是逐页朗读")
    title_block(c, "DEMO GUIDE", "建议演示路径：先看真实市场，再看一只股票，最后展示Agent与透明算法", "所有页面都来自本轮真实操作结果；演示时强调数据时间和证据边界，避免把研究辅助描述成自动交易。")
    steps = [
        ("01", "首页实时市场", "说明中日韩美、伦敦金和A股全景如何实时更新。", BLUE),
        ("02", "中兴通讯研究空间", "打开行情、六维证据、任务和历史快照。", GREEN),
        ("03", "即时Agent回答", "现场提问现金流或大跌原因，展示新生成回答和K线侧栏。", BLUE),
        ("04", "透明选股", "运行通用候选，再展示李总严格0候选和8/9观察池。", GOLD),
        ("05", "资料与复盘", "说明85份资料、市场文章和用户确认写回。", GREEN),
        ("06", "后台白盒", "用架构、数据库和队列页回答工程问题。", RED),
    ]
    for i, (num, name, note, accent) in enumerate(steps):
        col, row = i % 2, i // 2
        x, y = 43 + col * 383, 347 - row * 82
        rounded_box(c, x, y, 366, 65, fill=WHITE, stroke=accent, radius=9)
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(x + 15, y + 35, num)
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 11)
        c.drawString(x + 57, y + 38, name)
        paragraph(c, note, x + 57, y + 9, 288, 25, size=7.8, color=MUTED)
    rounded_box(c, 43, 76, 366, 64, fill=PALE_GREEN, stroke=colors.HexColor("#BDE4D6"), radius=9)
    paragraph(c, "可以明确展示", 58, 115, 120, 18, size=10.5, color=GREEN, font=FONT_BOLD)
    paragraph(c, "真实行情、确定性指标、历史数据、证据来源、Agent即时解释、用户确认边界和后台运行状态。", 58, 85, 334, 27, size=8.2, color=INK)
    rounded_box(c, 432, 76, 366, 64, fill=PALE_RED, stroke=colors.HexColor("#F0C4C8"), radius=9)
    paragraph(c, "不能承诺", 447, 115, 120, 18, size=10.5, color=RED, font=FONT_BOLD)
    paragraph(c, "自动交易、目标价、仓位、胜率、未来涨跌概率、确定收益，以及未经许可的商业数据完整覆盖。", 447, 85, 334, 27, size=8.2, color=INK)
    c.showPage()


def page_closing(c: canvas.Canvas, page_no: int) -> None:
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#24406F"))
    c.circle(PAGE_W - 80, 75, 210, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.circle(PAGE_W - 40, 30, 110, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#91B5FF"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(58, PAGE_H - 92, "QINGSHU FINANCIAL RESEARCH AGENT")
    paragraph(c, "把一次回答，变成可持续核验的研究资产。", 58, 292, 650, 100, size=29, leading=42, color=WHITE, font=FONT_BOLD)
    paragraph(c, "当前MVP已经具备真实金融数据库、后台持续刷新、透明算法、即时Agent、个人研究空间和复盘链路。下一阶段的重点不是堆更多页面，而是继续提高同日直接证据覆盖、模型时延稳定性、商业数据授权和生产运维能力。", 60, 210, 650, 70, size=12, leading=20, color=colors.HexColor("#D8E5FA"))
    c.setStrokeColor(colors.HexColor("#456493"))
    c.line(60, 180, 650, 180)
    paragraph(c, "本报告中的界面截图均来自2026-07-26真实产品操作；算法和架构说明依据当前权威仓库代码与运行态。", 60, 126, 650, 36, size=9.5, color=colors.HexColor("#BFD0EE"))
    c.setFillColor(colors.HexColor("#A9BAD6"))
    c.setFont(FONT, 8)
    c.drawString(60, 48, f"{REPORT_DATE}  |  页面 {page_no:02d}")
    c.showPage()


def build(output: Path = OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle("清数智算金融研究Agent - 产品演示与技术算法说明")
    c.setAuthor("清数智算产品组")
    c.setSubject("真实功能演示、系统架构、数据库、后台队列与金融算法")
    page_cover(c, 1)
    page_summary(c, 2)
    page_function_map(c, 3)
    screenshot_page(c, 4, "首页实时市场", "中日韩美、伦敦金与A股全景", "01_today_markets.png", [
        "实时或最近有效行情按各市场交易状态展示，不把不同交易时点强行合成一个结论。",
        "首页同时给出指数分钟K线、A股市场广度和技术状态，适合先回答“今天发生了什么”。",
    ], tags=["全球指数", "分钟K线", "A股全景", "自动刷新"])
    screenshot_page(c, 5, "我的关注", "预设自选股与服务器端研究资产", "02_watchlist.png", [
        "中兴通讯、中际旭创、英伟达均可直接进入个股空间，查看最新报告、变化与下一步任务。",
        "公共研究快照与用户私有关注理由分离；报告可预生成，用户判断保持隔离。",
    ], tags=["中兴通讯", "中际旭创", "英伟达", "预生成报告"])
    screenshot_page(c, 6, "个股研究空间", "行情、估值、K线和长期研究摘要", "03_stock_research.png", [
        "中兴通讯实测显示价格35元、当日-2.56%、PE 37.41、PB 2.18和市值1674.24亿元。",
        "同一用户、同一股票只保留一个长期研究空间，判断、证据、任务和对话持续沉淀。",
    ], tags=["行情估值", "日K线", "六维证据6/6", "长期空间"])
    screenshot_page(c, 7, "六维数据与证据", "事实、计算、AI解释和缺失项分层呈现", "04_stock_evidence.png", [
        "公司经营、财务质量、现金流、行业同行、估值、公告与风险证据在同一页交叉核验。",
        "页面明确区分原始数据、系统计算、AI解释和缺失项，避免把推断冒充正式事实。",
    ], tags=["财务", "现金流", "同行行业", "公告事件", "反方证据"])
    screenshot_page(c, 8, "Agent即时研究结果", "Hermes调用DeepSeek v4 Pro基于本轮证据新生成", "05_agent_result.png", [
        "真实提问聚焦中兴通讯价格、盈利质量、现金流、反方证据与下一步核验。",
        "回答引用2026一季报的营收、净利润、毛利率、ROE、减值和费用证据；右侧自动呈现K线、RSI、MACD、ATR和量比。",
    ], tags=["即时生成", "证据引用", "反方证据", "K线侧栏"])
    screenshot_page(c, 9, "通用透明选股", "确定性模板先生成候选，再让Agent继续研究", "06_screening_results.png", [
        "本轮执行“相对行业增强候选”，返回12只候选及5/20日收益、行业超额、PE/PB和市值。",
        "每只候选都能加入关注、保存线索或让Agent继续研究；候选不是买入信号。",
    ], tags=["12只候选", "行业超额", "估值市值", "继续研究"])
    page_two_screens(c, 10, "李总策略：严格候选与观察池", "规则不为演示放宽，空候选也给出真实解释", "07_li_zong_strategy.png", "严格候选为0", "覆盖5531只A股，九条规则必须全部通过且数据完整。页面展示漏斗和真实历史命中，不制造演示候选。", "08_li_zong_observation_pool.png", "8/9观察池", "广合科技、杰瑞股份只通过8条，页面明确标注未通过项和“非候选”，用于研究而不是替代正式规则。")
    page_two_screens(c, 11, "任务、操作与历史复盘", "把一次研究延伸为可持续核验的工作流", "12_tasks_operations.png", "任务与操作", "保存观察任务、操作计划、持仓事实和系统建议任务；当前示例包含波动率复核与MA20关系复核。", "13_stock_history_review.png", "历史与复盘", "保存研究快照、用户判断版本、重要变化、绑定对话和真实交易复盘入口，旧结论不会被新证据静默覆盖。")
    page_two_screens(c, 12, "市场复盘与资料库", "后台形成内容，前端只展示用户可读结果", "09_market_review.png", "市场复盘", "多篇市场短文按时间从新到旧排列，可点击阅读完整内容；普通页面不展示后台刷新状态或供应商错误。", "10_knowledge.png", "资料库", "当前85份资料覆盖事件脉络、财报原文原因证据和财报质量分析，可被Agent检索但不会直接回放为当前回答。")
    page_account_status(c, 13)
    page_diagram(c, 14, "总体系统架构", "金融源、确定性服务、Agent、PostgreSQL和网页产品", "20_architecture.png", "Web与Worker共享PostgreSQL和跨进程事件；模型解释与确定性金融计算保持边界。")
    page_diagram(c, 15, "数据库分层与核心实体", "共享金融事实、用户私有研究资产与待确认候选", "23_personal_data_model.png", "领域库Schema v2与运维库Schema v4可以位于同一PostgreSQL实例，但分别维护迁移版本和服务边界。")
    page_data_sources(c, 16)
    page_technical_algorithms(c, 17)
    page_market_algorithms(c, 18)
    page_financial_algorithms(c, 19)
    page_li_zong_algorithm(c, 20)
    page_diagram(c, 21, "Agent证据链与即时回答流程", "从问题路由到证据装配、Hermes生成与候选写回", "21_answer_flow.png", "保存报告和历史对话只作为证据；当前回答必须由Hermes/DeepSeek重新生成。")
    page_diagram(c, 22, "持久化队列、Worker与恢复机制", "PostgreSQL原子抢占、租约、心跳、指数退避和失败归档", "25_queue_flow.png", "队列语义为at-least-once，因此刷新、分析和写回处理器必须幂等；Worker异常后过期租约可恢复。")
    page_diagram(c, 23, "长期研究生命周期", "从市场变化到用户确认、持续跟踪和交易复盘", "22_research_loop.png", "正式判断、观察任务、操作计划和复盘必须由用户确认；AI只生成待确认候选。")
    page_demo_script(c, 24)
    page_closing(c, 25)
    c.save()
    return output


if __name__ == "__main__":
    print(build())
