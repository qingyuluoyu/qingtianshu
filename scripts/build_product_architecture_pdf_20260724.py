from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "清数智算MVP产品功能架构与质量复盘报告-20260724.pdf"
ASSET_ROOT = Path(
    "/Users/chr/Documents/青树金融交易/qingshu-agent-demo/report_assets_20260723"
)

PAGE = landscape(A4)
PAGE_W, PAGE_H = PAGE
MARGIN_X = 13 * mm
TOP = 16 * mm
BOTTOM = 12 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

NAVY = colors.HexColor("#0F2B4C")
BLUE = colors.HexColor("#3478F6")
BLUE_LIGHT = colors.HexColor("#EAF1FF")
TEAL = colors.HexColor("#1BAE8D")
TEAL_LIGHT = colors.HexColor("#E6F8F3")
AMBER = colors.HexColor("#D18B12")
AMBER_LIGHT = colors.HexColor("#FFF4D9")
RED = colors.HexColor("#D94B5B")
RED_LIGHT = colors.HexColor("#FDECEF")
TEXT = colors.HexColor("#17233C")
MUTED = colors.HexColor("#66758C")
LINE = colors.HexColor("#DCE4F0")
BG = colors.HexColor("#F6F8FC")
WHITE = colors.white


def register_fonts() -> tuple[str, str]:
    regular = Path("/Users/chr/Library/Fonts/NotoSansCJKsc-Regular.otf")
    if regular.exists():
        pdfmetrics.registerFont(TTFont("QingShuSans", str(regular)))
        return "QingShuSans", "QingShuSans"
    return "STSong-Light", "STSong-Light"


FONT, FONT_BOLD = register_fonts()

styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "TitleCN",
    parent=styles["Title"],
    fontName=FONT_BOLD,
    fontSize=26,
    leading=34,
    textColor=NAVY,
    spaceAfter=6 * mm,
)
SUBTITLE = ParagraphStyle(
    "SubtitleCN",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=12,
    leading=18,
    textColor=MUTED,
)
H1 = ParagraphStyle(
    "H1CN",
    parent=styles["Heading1"],
    fontName=FONT_BOLD,
    fontSize=20,
    leading=27,
    textColor=NAVY,
    spaceAfter=4 * mm,
)
H2 = ParagraphStyle(
    "H2CN",
    parent=styles["Heading2"],
    fontName=FONT_BOLD,
    fontSize=13,
    leading=18,
    textColor=NAVY,
    spaceAfter=2 * mm,
)
BODY = ParagraphStyle(
    "BodyCN",
    parent=styles["BodyText"],
    fontName=FONT,
    fontSize=9.6,
    leading=15,
    textColor=TEXT,
    spaceAfter=1.6 * mm,
)
BODY_SMALL = ParagraphStyle(
    "BodySmallCN",
    parent=BODY,
    fontSize=8.3,
    leading=12.5,
)
CAPTION = ParagraphStyle(
    "CaptionCN",
    parent=BODY_SMALL,
    fontSize=7.8,
    leading=11,
    textColor=MUTED,
    alignment=TA_CENTER,
)
CARD_TITLE = ParagraphStyle(
    "CardTitleCN",
    parent=BODY,
    fontName=FONT_BOLD,
    fontSize=11,
    leading=15,
    textColor=NAVY,
    alignment=TA_LEFT,
)
METRIC = ParagraphStyle(
    "MetricCN",
    parent=BODY,
    fontName=FONT_BOLD,
    fontSize=21,
    leading=24,
    textColor=BLUE,
    alignment=TA_CENTER,
)
METRIC_LABEL = ParagraphStyle(
    "MetricLabelCN",
    parent=BODY_SMALL,
    fontSize=8,
    leading=11,
    textColor=MUTED,
    alignment=TA_CENTER,
)
TABLE_HEAD = ParagraphStyle(
    "TableHeadCN",
    parent=BODY_SMALL,
    fontName=FONT_BOLD,
    textColor=WHITE,
    alignment=TA_CENTER,
)
TABLE_BODY = ParagraphStyle(
    "TableBodyCN",
    parent=BODY_SMALL,
    fontSize=7.7,
    leading=11,
)


def p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str], style: ParagraphStyle = BODY) -> list[Paragraph]:
    return [
        Paragraph(f"• {item}", ParagraphStyle(f"bullet-{index}", parent=style, leftIndent=8))
        for index, item in enumerate(items)
    ]


def page_title(title: str, kicker: str | None = None) -> list:
    result: list = [Paragraph(title, H1)]
    if kicker:
        result.append(Paragraph(kicker, SUBTITLE))
        result.append(Spacer(1, 3 * mm))
    return result


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, 8 * mm, PAGE_W - MARGIN_X, 8 * mm)
    canvas.setFont(FONT, 7.2)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN_X, 4.5 * mm, "清数智算 MVP · 产品功能、架构与质量复盘")
    canvas.drawRightString(
        PAGE_W - MARGIN_X,
        4.5 * mm,
        f"2026-07-24  |  {doc.page}",
    )
    canvas.restoreState()


def fit_image(path: Path, width: float, height: float) -> Image:
    image = Image(str(path))
    ratio = min(width / image.imageWidth, height / image.imageHeight)
    image.drawWidth = image.imageWidth * ratio
    image.drawHeight = image.imageHeight * ratio
    return image


def metric_cards(items: list[tuple[str, str, str]]) -> Table:
    cells = []
    for value, label, note in items:
        cells.append(
            [
                Paragraph(value, METRIC),
                Paragraph(label, METRIC_LABEL),
                Paragraph(note, CAPTION),
            ]
        )
    table = Table(
        [[Table(cell, colWidths=[CONTENT_W / len(items) - 7 * mm]) for cell in cells]],
        colWidths=[CONTENT_W / len(items)] * len(items),
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ]
        )
    )
    return table


def two_cards(
    left_title: str,
    left_items: list[str],
    right_title: str,
    right_items: list[str],
    *,
    left_color=BLUE_LIGHT,
    right_color=TEAL_LIGHT,
) -> Table:
    left = [Paragraph(left_title, CARD_TITLE), Spacer(1, 2 * mm), *bullets(left_items)]
    right = [Paragraph(right_title, CARD_TITLE), Spacer(1, 2 * mm), *bullets(right_items)]
    table = Table(
        [[left, right]],
        colWidths=[CONTENT_W * 0.49, CONTENT_W * 0.49],
        hAlign="CENTER",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), left_color),
                ("BACKGROUND", (1, 0), (1, 0), right_color),
                ("BOX", (0, 0), (-1, -1), 0.8, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]
        )
    )
    return table


def labeled_table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[Paragraph(value, TABLE_HEAD) for value in headers]]
    data.extend([[Paragraph(value, TABLE_BODY) for value in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    return table


def frontend_architecture() -> Drawing:
    d = Drawing(CONTENT_W, 310)
    columns = [
        (
            8,
            NAVY,
            "入口与导航",
            ["今日观察", "我的关注", "个股研究", "AI研究", "复盘中心", "个人中心"],
        ),
        (
            205,
            BLUE,
            "页面工作区",
            ["全球行情", "股票空间", "诊大盘/诊个股", "智能选股", "李总策略", "历史会话"],
        ),
        (
            402,
            TEAL,
            "交互状态",
            ["行情/K线", "证据抽屉", "Agent流式回答", "任务与判断", "持仓操作", "复盘草稿"],
        ),
        (
            599,
            AMBER,
            "服务边界",
            ["FastAPI 页面/API", "SSE 事件", "用户会话隔离", "数据健康", "失败重试", "后端不暴露运维噪声"],
        ),
    ]
    for x, color, title, items in columns:
        d.add(Rect(x, 40, 176, 235, 12, 12, fillColor=colors.Color(color.red, color.green, color.blue, alpha=0.08), strokeColor=color, strokeWidth=1.3))
        d.add(Rect(x, 232, 176, 43, 12, 12, fillColor=color, strokeColor=color))
        d.add(String(x + 88, 246, title, fontName=FONT, fontSize=12, fillColor=WHITE, textAnchor="middle"))
        y = 205
        for item in items:
            d.add(Rect(x + 15, y - 7, 146, 26, 7, 7, fillColor=WHITE, strokeColor=LINE))
            d.add(String(x + 88, y + 2, item, fontName=FONT, fontSize=8.8, fillColor=TEXT, textAnchor="middle"))
            y -= 31
    for x1, x2 in [(184, 205), (381, 402), (578, 599)]:
        d.add(Line(x1, 157, x2, 157, strokeColor=MUTED, strokeWidth=1.3))
    d.add(String(8, 15, "当前形态：功能完整度高，但页面仍以单体 HTML 为主，后续应组件化而非继续堆叠信息。", fontName=FONT, fontSize=9, fillColor=MUTED))
    return d


def agent_architecture() -> Drawing:
    d = Drawing(CONTENT_W, 305)
    layers = [
        (245, NAVY, "用户问题与会话上下文", "股票/市场/选股/复盘意图；继承历史焦点"),
        (190, BLUE, "Hermes 编排 + DeepSeek v4 Pro", "ResearchPlan、Skills 路由、工具调用、流式生成"),
        (135, TEAL, "本轮证据包", "行情、财务、公告、新闻、行业、用户资料与长期知识"),
        (80, AMBER, "结构化研究合同", "Claim / Citation / 反方证据 / 失效条件 / 下一证据"),
        (25, NAVY, "用户确认后的正式事实", "判断、任务、计划、复盘只写候选；用户确认后落库"),
    ]
    for y, color, title, desc in layers:
        d.add(Rect(80, y, CONTENT_W - 160, 42, 10, 10, fillColor=color, strokeColor=color))
        d.add(String(230, y + 17, title, fontName=FONT, fontSize=11, fillColor=WHITE, textAnchor="middle"))
        d.add(String(CONTENT_W - 100, y + 17, desc, fontName=FONT, fontSize=9, fillColor=WHITE, textAnchor="end"))
        if y > 25:
            d.add(Line(CONTENT_W / 2, y - 12, CONTENT_W / 2, y, strokeColor=MUTED, strokeWidth=1.2))
    return d


def backend_architecture() -> Drawing:
    d = Drawing(CONTENT_W, 320)
    d.add(Rect(15, 230, 740, 55, 12, 12, fillColor=BLUE_LIGHT, strokeColor=BLUE))
    d.add(String(385, 260, "Web / API 进程", fontName=FONT, fontSize=14, fillColor=NAVY, textAnchor="middle"))
    d.add(String(385, 242, "FastAPI · 用户页面 · REST/SSE · /health liveness · /ready readiness", fontName=FONT, fontSize=9, fillColor=TEXT, textAnchor="middle"))
    d.add(Rect(15, 130, 355, 70, 12, 12, fillColor=TEAL_LIGHT, strokeColor=TEAL))
    d.add(String(192, 172, "PostgreSQL 业务与运维主库", fontName=FONT, fontSize=12, fillColor=NAVY, textAnchor="middle"))
    d.add(String(192, 152, "74 张表 · 业务 Schema v1 · 运维 Schema v4", fontName=FONT, fontSize=9, fillColor=TEXT, textAnchor="middle"))
    d.add(String(192, 137, "用户/会话/研究/证据/队列/计划/Worker/审计", fontName=FONT, fontSize=8.5, fillColor=MUTED, textAnchor="middle"))
    d.add(Rect(400, 130, 355, 70, 12, 12, fillColor=AMBER_LIGHT, strokeColor=AMBER))
    d.add(String(577, 172, "独立持久化 Worker", fontName=FONT, fontSize=12, fillColor=NAVY, textAnchor="middle"))
    d.add(String(577, 152, "幂等 · 优先级 · 租约 · 心跳 · 重试 · 失败归档", fontName=FONT, fontSize=9, fillColor=TEXT, textAnchor="middle"))
    d.add(String(577, 137, "PostgreSQL 原子抢占；可多 Worker 扩展", fontName=FONT, fontSize=8.5, fillColor=MUTED, textAnchor="middle"))
    d.add(Rect(15, 35, 355, 65, 12, 12, fillColor=WHITE, strokeColor=NAVY))
    d.add(String(192, 75, "金融数据与模型 Provider", fontName=FONT, fontSize=11, fillColor=NAVY, textAnchor="middle"))
    d.add(String(192, 55, "Tushare 兼容源、交易所/公告/新闻、Hermes/DeepSeek", fontName=FONT, fontSize=8.8, fillColor=TEXT, textAnchor="middle"))
    d.add(Rect(400, 35, 355, 65, 12, 12, fillColor=WHITE, strokeColor=NAVY))
    d.add(String(577, 75, "备份、恢复与运维", fontName=FONT, fontSize=11, fillColor=NAVY, textAnchor="middle"))
    d.add(String(577, 55, "pg_dump custom · SHA-256 · 恢复演练 · 保留策略 · 运行手册", fontName=FONT, fontSize=8.8, fillColor=TEXT, textAnchor="middle"))
    for x in (192, 577):
        d.add(Line(x, 215, x, 230, strokeColor=MUTED, strokeWidth=1.3))
        d.add(Line(x, 100, x, 130, strokeColor=MUTED, strokeWidth=1.3))
    d.add(Line(370, 165, 400, 165, strokeColor=MUTED, strokeWidth=1.3))
    return d


def build_story() -> list:
    story: list = []

    # 1. Cover
    story.extend(
        [
            Spacer(1, 18 * mm),
            Paragraph("清数智算 MVP", TITLE),
            Paragraph("产品功能、Agent/金融分析架构与质量复盘报告", TITLE),
            Paragraph(
                "基于权威仓库、真实浏览器验收截图、全量自动化、PostgreSQL 迁移、持久化队列与恢复演练",
                SUBTITLE,
            ),
            Spacer(1, 13 * mm),
            metric_cards(
                [
                    ("626", "自动化收集项", "常规环境 619 通过 / 7 跳过"),
                    ("212,103", "真实迁移行数", "72 张迁移表，66 张非空"),
                    ("20", "持久化周期计划", "独立 Worker，零积压"),
                    ("54 / 54", "数据健康检查", "当前状态 healthy"),
                ]
            ),
            Spacer(1, 12 * mm),
            p(
                "<b>一句话定位：</b>面向个人投资者的证据驱动金融研究工作台。它把实时行情、财务与资讯、透明选股、个股长期研究空间、即时 Agent 对话、任务计划和交易复盘连接成一条可追溯闭环。",
                ParagraphStyle("cover-note", parent=BODY, fontSize=12, leading=19),
            ),
            Spacer(1, 8 * mm),
            HRFlowable(width="100%", thickness=1, color=LINE),
            Spacer(1, 4 * mm),
            p(
                "版本快照：codex/structured-ai-writeback · 97d3464 · 2026-07-24 20:00-20:06 CST 实测",
                CAPTION,
            ),
            PageBreak(),
        ]
    )

    # 2. Executive summary
    story.extend(page_title("01｜当前结论", "产品已跨过“展示 Demo”阶段，但仍需继续做体验收敛和外部生产化。"))
    story.append(
        two_cards(
            "已经真正实现",
            [
                "中、日、韩、美与伦敦金行情，开盘市场自动更新当日 K 线；A 股市场广度、成交额与涨跌分布。",
                "中兴通讯、中际旭创、英伟达等自选股服务器预分析；行情、财务、公告、行业、研报和反方证据进入股票长期空间。",
                "Hermes + DeepSeek v4 Pro 即时回答，按问题动态组织证据，不把数据库中的预存文案直接当答案。",
                "通用选股、李总策略、历史点时回放、任务计划、持仓/操作记录和用户确认后的交易复盘。",
                "真实 PostgreSQL 主库、持久化队列、独立 Worker、就绪探针、备份、恢复演练和运行手册。",
            ],
            "仍未达到的边界",
            [
                "正式账户体系、生产密钥管理、外部告警、真实 staging 服务器和 CI Workflow 尚未闭合。",
                "用户工作区文件仍依赖本地/共享卷；PostgreSQL 备份不覆盖上传文件和 Run 目录。",
                "部分研究报告仍可能处于 partial/degraded，需继续提高证据覆盖率和数据源 SLA。",
                "前端功能丰富但信息密度偏高，单体 HTML 体量大，组件化和全站一致性仍不足。",
                "任何选股、走势描述和复盘均是研究辅助，不自动形成荐股、目标价或交易指令。",
            ],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        labeled_table(
            ["评估维度", "当前判断", "说明"],
            [
                ["面向用户的 R1 研究闭环", "较高完成度", "研究 → 判断 → 任务 → 操作 → 冻结证据 → AI 草稿 → 用户确认已连通。"],
                ["选股与个股分析可信度", "可用但持续增强", "确定性规则与证据边界清晰；仍需扩大同口径同行比较与点时覆盖。"],
                ["内部测试版生产底座", "已具备", "PostgreSQL、持久化队列、Worker、备份恢复与 readiness 已实测。"],
                ["外部用户正式生产", "未完成", "认证、密钥、对象存储、监控告警、staging 和发布自动化仍是门槛。"],
            ],
            [42 * mm, 38 * mm, CONTENT_W - 80 * mm],
        )
    )
    story.append(PageBreak())

    # 3. Frontend architecture
    story.extend(page_title("02｜前端信息架构与用户路径", "六大一级入口围绕“发现问题、持续研究、记录行动、复盘决策”组织。"))
    story.append(frontend_architecture())
    story.append(Spacer(1, 2 * mm))
    story.append(
        p(
            "<b>体验判断：</b>当前导航和页面能力已经完整，但首页和股票空间的信息量较大。下一轮优化应优先做视觉层级、默认折叠、上下文就近呈现和共享组件，不再简单增加卡片。",
            BODY,
        )
    )
    story.append(PageBreak())

    # 4. Home screenshot
    story.extend(page_title("03｜首页：全球行情与 A 股全景", "真实浏览器验收截图（2026-07-23）；今天后端实时状态通过 API 与 PostgreSQL 再次验证。"))
    home = fit_image(ASSET_ROOT / "首页_全球行情与A股全景.png", CONTENT_W, 355)
    story.append(home)
    story.append(Spacer(1, 2 * mm))
    story.append(
        labeled_table(
            ["用户看到什么", "产品内部在做什么", "需要继续优化"],
            [
                ["正在交易的市场、价格、涨跌和当日 K 线；A 股核心指数与市场结构。", "定时刷新行情、市场新闻、广度、成交额和涨跌分布；后台不向用户暴露“信息源不可用”等运维文本。", "“今日需处理”不应压过行情主任务；文章/研究更新区应支持按时间滚动浏览。"],
            ],
            [65 * mm, 100 * mm, CONTENT_W - 165 * mm],
        )
    )
    story.append(PageBreak())

    # 5. Stock workspace
    story.extend(page_title("04｜个股研究空间：一只股票、一条长期研究主线", "研究概览、AI 研究、数据与证据、任务与操作、历史与复盘统一在同一股票空间。"))
    stock = fit_image(ASSET_ROOT / "个股研究_中兴通讯概览.png", CONTENT_W, 355)
    story.append(stock)
    story.append(Spacer(1, 2 * mm))
    story.append(
        two_cards(
            "空间内的确定性事实",
            [
                "最新报价、完整日线、技术指标和估值快照。",
                "报告期财务、现金流质量、业务构成、股东与同行证据。",
                "公告/新闻事件、证据日期、数据来源与覆盖状态。",
            ],
            "空间内的用户与 AI 事实",
            [
                "用户确认的判断版本、关系与研究理由。",
                "观察任务、操作计划、持仓与操作记录。",
                "Agent 对话、报告、反方证据、失效条件和复盘历史。",
            ],
        )
    )
    story.append(PageBreak())

    # 6. Conversation
    story.extend(page_title("05｜Agent 对话：即时生成，而不是播放预存答案", "历史材料只作为证据；本轮问题决定 ResearchPlan、工具调用与回答结构。"))
    chat = fit_image(ASSET_ROOT / "个股Agent_连续研究对话.png", CONTENT_W, 355)
    story.append(chat)
    story.append(Spacer(1, 2 * mm))
    story.append(
        labeled_table(
            ["交互能力", "已实现合同", "质量边界"],
            [
                ["多会话、历史恢复、Enter 发送、股票/市场上下文继承", "问题路由 → 证据准备 → 模型流式生成 → 引用与候选写回", "模型不可用时显示显式失败与原位重试；不能用确定性摘要冒充正常生成。"],
                ["诊大盘、诊个股、个股空间内嵌 Agent", "回答需包含事实、反方证据、失效条件和下一核验", "不输出目标价、胜率、确定涨跌或自动买卖建议。"],
            ],
            [62 * mm, 108 * mm, CONTENT_W - 170 * mm],
        )
    )
    story.append(PageBreak())

    # 7. Agent architecture
    story.extend(page_title("06｜Agent 内在逻辑", "Hermes 负责计划和工具编排，DeepSeek v4 Pro 负责本轮生成，数据库保存证据与历史，不保存“万能答案”。"))
    story.append(agent_architecture())
    story.append(Spacer(1, 3 * mm))
    story.append(
        two_cards(
            "为何比普通 LLM 对话更可靠",
            [
                "金融数字由工具与数据库给出，模型只做解释和证据组织。",
                "每轮回答绑定当前问题、数据时间、报告期与引用。",
                "Claim Ledger 区分支持、反证、未决和失效条件。",
                "用户资料库与通用资料库分层，用户之间隔离。",
            ],
            "为何仍需持续测试",
            [
                "意图路由、同名实体和连续追问可能产生上下文偏移。",
                "数据缺失、模型超时和流式连接中断必须原位恢复。",
                "较长回答需要压缩、分层与可读性优化。",
                "正式事实写回必须保持“AI 候选，用户确认”。",
            ],
        )
    )
    story.append(PageBreak())

    # 8. Financial evidence
    story.extend(page_title("07｜金融数据与分析层", "目标不是堆指标，而是让每个结论能追到数据口径、时间和反方证据。"))
    story.append(
        labeled_table(
            ["分析域", "当前能力", "关键口径"],
            [
                ["市场与板块", "全球指数、A 股核心指数、广度、成交额、分布、行业指数与资讯驱动", "盘中时间、日线交易日、代表性指数与全市场广度严格区分。"],
                ["个股行情", "实时/延迟报价、复权日线、MA/RSI/MACD/ATR、区间收益与回撤", "技术状态只描述当前证据，不直接预测下一交易日。"],
                ["基本面", "财务三表、ROE、利润率、现金流、主营构成、盈利质量和财务驱动", "财务报告期、公告日和行情日分开保存。"],
                ["公司与行业", "公告、新闻、研报、股东结构、同行估值和同报告期经营比较", "跨市场、混合币种和不同报告期时禁止伪排名。"],
                ["研究结论", "支持证据、反方证据、失效条件、下一证据与历史结果校准", "历史材料是证据快照；当前结论必须由本轮模型重新生成。"],
            ],
            [34 * mm, 112 * mm, CONTENT_W - 146 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        two_cards(
            "后台自动任务",
            [
                "开盘市场行情、A 股全景与市场新闻。",
                "财务、公告、业务构成、股东和同行估值。",
                "自选股研究报告、研究结果回填和校准。",
                "李总策略全市场筛选与近期历史回放。",
            ],
            "用户看不到的运维噪声",
            [
                "供应商异常类型、缓存状态和内部错误码。",
                "后台文章生成、队列名称和 Worker 内部日志。",
                "“信息源不可用”等不具备用户行动价值的文字。",
                "管理员健康、计划暂停/恢复和备份详情。",
            ],
        )
    )
    story.append(PageBreak())

    # 9. Screening
    story.extend(page_title("08｜选股与李总策略：透明规则，不是黑盒荐股", "候选由确定性规则产生，Agent 只解释结果、缺口和下一步核验。"))
    story.append(
        labeled_table(
            ["模块", "规则与结果", "边界"],
            [
                ["通用选股", "自然语言条件转为显式筛选；返回覆盖率、数据版本、命中原因和缺失原因。", "不输出综合分、星级、目标价或“最值得买”。结果为空时只建议逐项放宽。"],
                ["李总候选池", "9 条候选规则：市值、连续年度 ROE、机构持股、涨停性格、近期阴线、复权新高、量能等。", "9/9 全部通过才是候选；数据不完整不会进入候选。"],
                ["李总触发层", "3 条候选后触发：当日涨停、跳空高开、振幅条件。", "触发只决定候选后的重点复核，不是候选资格。"],
                ["观察层", "8/9 接近满足、6-7/9 研究观察；显示明确失败规则。", "观察池不是候选、概率、排名或推荐。"],
                ["历史回放", "信号日点时数据、沪深300 5/10/20 日对照、最大上行/下行与累计路径。", "当前是近期约 80 个可计算交易日；未计交易成本、涨跌停可成交性和实际成交价。"],
            ],
            [35 * mm, 115 * mm, CONTENT_W - 150 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        p(
            "<b>当前实测快照：</b>全市场 5,530 只股票覆盖率 100%，严格候选为 0；这不是系统失败，而是规则在当期没有同时满足者。产品用真实筛选漏斗和观察层解释“为什么为空”，不会伪造候选。",
            ParagraphStyle("screen-note", parent=BODY, backColor=AMBER_LIGHT, borderColor=AMBER, borderWidth=0.6, borderPadding=8),
        )
    )
    story.append(PageBreak())

    # 10. R1 loop
    story.extend(page_title("09｜从研究到复盘的可追溯闭环", "价格结果由代码计算，逻辑结果由 AI 起草，最终事实由用户确认。"))
    loop = fit_image(ASSET_ROOT / "交易复盘闭环_20260723.png", CONTENT_W, 340)
    story.append(loop)
    story.append(Spacer(1, 2 * mm))
    story.append(
        p(
            "操作发生时冻结当时判断、计划、持仓、价格、指数、行业、估值和重要变化；三个完整交易日后才进入复盘。盈利不自动证明逻辑正确，亏损也不自动证明逻辑错误。AI 只提供可编辑草稿，用户确认后归档。",
            BODY,
        )
    )
    story.append(PageBreak())

    # 11. Tasks screenshot
    story.extend(page_title("10｜任务与操作：把研究变成可验证的下一步", "系统保存观察条件与计划，不自动执行交易，也不替用户生成仓位和金额。"))
    tasks = fit_image(ASSET_ROOT / "任务与操作_操作计划.png", CONTENT_W, 365)
    story.append(tasks)
    story.append(Spacer(1, 2 * mm))
    story.append(
        two_cards(
            "适合保存",
            [
                "需要核验的公告、现金流或业务兑现条件。",
                "判断失效条件、时间节点和复核触发条件。",
                "用户明确写下的操作计划和实际操作事实。",
            ],
            "系统不会做",
            [
                "不会自动下单或连接券商执行交易。",
                "不会根据模型建议自动生成数量、金额或仓位。",
                "不会把 AI 草稿直接写成正式任务、判断或复盘。",
            ],
        )
    )
    story.append(PageBreak())

    # 12. Backend
    story.extend(page_title("11｜后端生产架构", "今天已把真实运行库从 SQLite 迁入 PostgreSQL，并切换为 Web + 独立 Worker。"))
    story.append(backend_architecture())
    story.append(Spacer(1, 3 * mm))
    story.append(
        p(
            "<b>持久化队列能力：</b>幂等键、计划、优先级、租约、心跳、指数退避重试、失败归档、取消、人工重试、多 Worker 原子抢占、离线识别、分级保留、计划暂停/恢复和队列健康统计。",
            BODY,
        )
    )
    story.append(PageBreak())

    # 13. Verification
    story.extend(page_title("12｜生产数据库、队列与恢复验证", "以下数字均来自 2026-07-24 20:00-20:06 CST 的当前机器实测。"))
    story.append(
        metric_cards(
            [
                ("74", "PostgreSQL 表", "业务 v1 / 运维 v4"),
                ("1", "活跃独立 Worker", "external 模式"),
                ("0", "队列积压/过期租约", "失败率 0%"),
                ("241 MB", "最近备份", "归档与 SHA-256 通过"),
            ]
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        labeled_table(
            ["验证项", "结果", "证据"],
            [
                ["代码回归", "通过", "626 项收集；常规环境 619 passed / 7 skipped；PostgreSQL 专项 7 项真实通过。"],
                ["真实数据迁移", "通过", "72 张数据表迁移，66 张非空，共 212,103 行；用户工作区路径保持有效。"],
                ["运行态", "通过", "/health=ok；/ready=200；业务/运维后端均为 PostgreSQL；数据健康 54/54。"],
                ["持久化 Worker", "通过", "1 个 external Worker active；20 个周期计划；ready/delayed/retrying 均为 0。"],
                ["备份", "通过", "pg_dump custom 归档 241,216,792 bytes；archive_verified=true；SHA-256 已保存。"],
                ["恢复演练", "通过", "随机临时库恢复 74 张表，核对 users=28、persistent_jobs=1,848、schedules=20，临时库已删除。"],
            ],
            [43 * mm, 25 * mm, CONTENT_W - 68 * mm],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        p(
            "<b>尚未覆盖：</b>用户工作区文件快照、外部 Prometheus/云告警、正式 staging 服务器演练、生产认证和密钥管理。当前结果可称为“内部测试版生产底座已建立”，不能称为“外部正式生产已完成”。",
            ParagraphStyle("boundary", parent=BODY, backColor=RED_LIGHT, borderColor=RED, borderWidth=0.6, borderPadding=8),
        )
    )
    story.append(PageBreak())

    # 14. Colleague comparison
    story.extend(page_title("13｜同事方案对比：取长补短，不整体合并", "同事分支 qingtianshu 3.4 快照（1ab1ad8）更偏数据工具和前端工程；当前主线更偏完整研究闭环。"))
    story.append(
        labeled_table(
            ["维度", "当前主线优势", "同事方案优势", "取舍"],
            [
                ["产品闭环", "股票长期空间、用户确认写回、任务/持仓/操作/复盘、R1 E2E 更完整。", "高保真页面与若干聚合视图更直接。", "以当前领域模型为主，只吸收更清晰的展示组件。"],
                ["Agent", "Hermes/DeepSeek 即时生成、ResearchPlan、Skills、引用、反证与失败恢复。", "DeepSeek Gateway 边界较清晰。", "吸收网关抽象，不替换当前 Agent 主链。"],
                ["数据工具", "证据域更广，点时回放、研究结果校准和长期事实更完整。", "股票搜索、行情/财务/K线接口、申万同行原始证据更集中。", "优先吸收代码归一化、同行快照和缓存合同。"],
                ["前端工程", "业务页面多、真实用户链路已验收。", "HTML/CSS/JS 拆分、静态资源和 ETag 思路更好。", "组件化吸收，避免把旧页面整体覆盖回来。"],
                ["生产底座", "PostgreSQL、持久化队列、Worker、备份恢复和 readiness 已完成。", "该快照仍以旧本地形态为主。", "继续沿用当前主线。"],
                ["金融边界", "候选/观察/触发严格分层，不给目标价或黑盒评分。", "部分旧设计更偏综合评分与展示。", "不吸收评分、收益预测、reasoning_content 和固定演示数据。"],
            ],
            [30 * mm, 75 * mm, 68 * mm, CONTENT_W - 173 * mm],
        )
    )
    story.append(PageBreak())

    # 15. Absorption and issues
    story.extend(page_title("14｜吸收清单与产品问题优先级", "接下来不增加更多功能入口，优先把用户每天会用的路径做得更轻、更稳。"))
    story.append(
        two_cards(
            "值得吸收（P0/P1）",
            [
                "股票代码、简称和拼音搜索归一化。",
                "申万同行原始证据、同报告期比较与分位数。",
                "前端共享组件、CSS/JS 拆分和静态资源缓存。",
                "ETag、流式协议边界与统一 LLM Gateway。",
                "今日市场聚合和更克制的高保真个股页面。",
            ],
            "明确不吸收",
            [
                "整体合并同事分支或覆盖当前领域对象。",
                "固定演示数据、固定 Agent 回答或预存结论直出。",
                "综合评分、目标价、收益预测和黑盒荐股榜。",
                "向用户暴露 reasoning_content、供应商错误和运维噪声。",
                "先拆一次前端、马上再全面重写 Next.js 的重复工程。",
            ],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        labeled_table(
            ["优先级", "问题", "建议"],
            [
                ["P0", "首页层级仍偏杂，“今日需处理”不应压过用户最常看的行情和自选股研究。", "重排首页：市场状态 → 自选股变化 → 最新研究；任务入口后置并默认收起。"],
                ["P0", "Agent 长回答的信息层级和连续对话稳定性仍需真实用户测试。", "默认短结论 + 展开证据；持续做市场、个股、选股、多轮追问和故障注入。"],
                ["P1", "单体 demo.html 体量大，迭代容易造成样式与状态互相影响。", "按导航、股票空间、对话、复盘拆成共享组件；保留现有 API 和业务对象。"],
                ["P1", "部分研究证据仍为 partial/degraded。", "建立数据源 SLA、字段级重试、覆盖率看板和证据新鲜度门槛。"],
                ["P2", "内置浏览器自动化当前被 localhost URL 策略拦截。", "这是验收环境限制；继续保留 Chrome/仓库 Runner 验收和 API 证据，不把它误判为产品故障。"],
            ],
            [20 * mm, 110 * mm, CONTENT_W - 130 * mm],
        )
    )
    story.append(PageBreak())

    # 16. Roadmap
    story.extend(page_title("15｜下一阶段路线", "目标从“功能很多”切换为“每天真的能用、回答可信、失败可恢复”。"))
    story.append(
        labeled_table(
            ["阶段", "目标", "完成定义"],
            [
                ["A. 体验收敛", "首页层级、股票空间信息密度、Agent 短回答与证据展开、文章滚动区。", "核心任务 3 步以内；不显示运维噪声；桌面与移动端真实浏览器通过。"],
                ["B. 金融可信度", "同行同口径、公告与新闻交叉验证、证据覆盖率、个股报告质量。", "每个核心结论都有时间、来源、反证和下一核验；partial 状态逐步下降。"],
                ["C. Agent 稳定性", "多轮上下文、工具失败、模型超时、流式中断和原位重试。", "不跳答、不重复模板、不用预存文案冒充生成；失败后保留可用证据。"],
                ["D. 生产封口", "正式认证、密钥、对象存储、监控告警、staging、CI 与回滚演练。", "发布门禁自动化；备份同时覆盖数据库和工作区；可观测、可恢复。"],
                ["E. 真实用户验证", "邀请少量投资者连续使用选股、个股研究和复盘闭环。", "用实际留存、问题完成率和复盘质量决定后续功能，不以页面数量衡量进展。"],
            ],
            [34 * mm, 112 * mm, CONTENT_W - 146 * mm],
        )
    )
    story.append(Spacer(1, 7 * mm))
    story.append(
        p(
            "<b>最终判断：</b>清数智算目前最有价值的不是“又一个会聊股票的机器人”，而是把金融证据、用户长期研究、透明规则和复盘动作连接起来。下一步的竞争力来自更可靠的数据、更短更准的回答、更清晰的页面，以及持续可验证的真实使用闭环。",
            ParagraphStyle("final-note", parent=BODY, fontSize=12, leading=19, backColor=BLUE_LIGHT, borderColor=BLUE, borderWidth=0.8, borderPadding=10),
        )
    )
    story.append(PageBreak())

    # 17. Sources
    story.extend(page_title("附录｜证据来源与验收边界", "本报告只引用当前权威仓库、同事快照、既有真实截图和本轮实测。"))
    story.extend(
        bullets(
            [
                "权威仓库：/Users/chr/Documents/qingtianshu；分支 codex/structured-ai-writeback；提交 97d3464。",
                "同事方案：/Users/chr/Documents/青树金融交易/.github-upload-ruizhi/qingtianshu；ruizhi 快照 1ab1ad8。",
                "高保真设计：/Users/chr/Documents/青树金融交易/AI金融Agent产品方案/清数智算_七页高保真交互演示.html。",
                "真实操作截图：qingshu-agent-demo/report_assets_20260723；截图属于 2026-07-23 浏览器验收，不伪装成 2026-07-24 新截图。",
                "当前自动化：626 tests collected；常规环境 619 passed / 7 skipped；PostgreSQL 专项真实通过。",
                "当前运行态：/health 与 /ready、PostgreSQL 表/Schema、Worker、队列与备份恢复均在 2026-07-24 20:00-20:06 CST 重新实测。",
                "内置浏览器当前受 URL 安全策略限制，无法自动访问 127.0.0.1；Chrome 可正常访问，服务端 /demo=200。该限制列为验收环境问题，而非产品故障。",
            ],
            ParagraphStyle("sources", parent=BODY, fontSize=10.5, leading=17),
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(
        p(
            "金融说明：本产品用于研究辅助。行情、财务、新闻、规则筛选和 Agent 解释均可能存在延迟、缺失或口径差异，不构成投资建议、评级、收益承诺或自动交易指令。",
            ParagraphStyle("disclaimer", parent=BODY, backColor=AMBER_LIGHT, borderColor=AMBER, borderWidth=0.8, borderPadding=10),
        )
    )
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=PAGE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title="清数智算MVP产品功能架构与质量复盘报告-20260724",
        author="清数智算产品研发",
        subject="产品功能、Agent、金融分析、选股、生产架构与质量复盘",
    )
    document.build(build_story(), onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
