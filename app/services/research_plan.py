from __future__ import annotations

import re
from typing import Any

from app.services.stock_price_move import (
    is_deep_stock_price_move_question,
    is_stock_price_move_question,
)


class ResearchPlanService:
    """Build a deterministic, question-scoped evidence plan for stock chat."""

    CONTRACT_VERSION = "stock_research_plan_v1"

    MODULE_LABELS = {
        "market": "价格与技术结构",
        "company_information": "公告、新闻与情绪",
        "fundamentals": "财务与最新估值",
        "earnings_quality": "财报质量",
        "financial_drivers": "利润与现金流驱动",
        "business_structure": "主营业务结构",
        "shareholder_structure": "股东结构",
        "analyst_expectations": "分析师预期",
        "event_timeline": "重要事件脉络",
        "peer_comparison": "同行比较",
        "outlook_calibration": "历史条件走查",
    }

    _FOCUS_RULES = (
        (
            "relative_industry",
            "相对行业表现",
            (
                "相对行业",
                "相对板块",
                "行业指数",
                "行业增强",
                "行业走弱",
                "跑赢行业",
                "跑输行业",
                "超额收益",
            ),
        ),
        (
            "valuation_review",
            "估值约束质量核验",
            (
                "估值约束候选",
                "估值处于约束范围",
                "估值约束质量",
                "估值是否有支撑",
                "估值有没有支撑",
                "估值陷阱",
                "低估值陷阱",
            ),
        ),
        (
            "quality_review",
            "经营改善质量核验",
            (
                "经营改善候选",
                "经营指标开始改善",
                "经营指标改善",
                "改善是否有质量",
                "改善有没有质量",
                "改善质量",
                "财报到底好不好",
                "财报究竟好不好",
                "财报好不好",
                "财报质量",
                "业绩质量",
                "经营质量",
                "盈利质量",
            ),
        ),
        (
            "shareholder",
            "股东与持有人变化",
            (
                "股东",
                "户数",
                "十大股东",
                "持有人",
                "筹码",
                "人均持股",
                "机构持仓",
                "机构股东",
                "主要股东",
            ),
        ),
        (
            "business_growth",
            "主营增长逻辑",
            (
                "增长到底靠什么",
                "增长靠什么",
                "靠什么增长",
                "第二增长曲线",
                "第二曲线",
                "增长引擎",
            ),
        ),
        (
            "business",
            "主营业务与收入结构",
            (
                "主营",
                "业务结构",
                "产品结构",
                "收入构成",
                "收入结构",
                "收入来源",
                "收入来自哪里",
                "靠什么赚钱",
                "靠什么业务赚钱",
                "毛利来源",
                "地区收入",
                "分部",
            ),
        ),
        (
            "expectations",
            "分析师预期与研报",
            ("分析师", "一致预期", "研报", "评级", "eps", "机构预期", "预期修订"),
        ),
        (
            "financial",
            "财务质量、利润与现金流",
            (
                "财务",
                "财务压力",
                "财报",
                "业绩",
                "营收",
                "利润",
                "毛利",
                "现金流",
                "费用",
                "应收",
                "存货",
                "负债",
                "盈利",
            ),
        ),
        (
            "valuation",
            "估值与同行对照",
            (
                "估值",
                "市盈率",
                "市净率",
                "pe",
                "pb",
                "贵不贵",
                "同行",
                "可比公司",
                "比较",
                "对比",
                "经营差异",
            ),
        ),
        (
            "events",
            "公告、新闻与事件核验",
            (
                "公告",
                "新闻",
                "消息",
                "事件",
                "订单",
                "监管",
                "诉讼",
                "回购",
                "增持",
                "减持",
                "定增",
            ),
        ),
        (
            "price_cause",
            "行情涨跌原因",
            (
                "为什么跌",
                "为什么涨",
                "为什么下跌",
                "为什么上涨",
                "为何跌",
                "为何涨",
                "为何下跌",
                "为何上涨",
                "怎么跌了",
                "怎么涨了",
                "大跌",
                "大涨",
                "涨停",
                "跌停",
                "涨跌原因",
                "回撤原因",
                "回撤最可能",
                "下跌最可能",
            ),
        ),
        (
            "price_action",
            "价格与技术状态",
            (
                "下跌",
                "上涨",
                "走势",
                "技术面",
                "盘中",
                "收盘",
                "股价",
                "价格",
                "报价",
                "均线",
                "涨跌",
                "企稳",
                "止跌",
                "反转",
                "见底",
                "走平",
                "横盘",
                "今天表现",
                "今日表现",
                "今天怎么样",
                "今日怎么样",
            ),
        ),
    )

    _FOCUS_MODULES = {
        "relative_industry": {
            "required": ("market", "analyst_expectations"),
            "optional": (),
            # The analyst packet currently stores the verified industry mapping
            # and index constituents, but its consensus skill is irrelevant to
            # a same-day relative-performance answer.
            "skills": (),
        },
        "price_cause": {
            "required": (
                "market",
                "company_information",
                "event_timeline",
            ),
            "optional": (),
            "skills": (
                "a-share-information",
                "event-timeline",
            ),
        },
        "price_action": {
            "required": (
                "market",
                "fundamentals",
            ),
            "optional": (),
            "skills": (
                "fundamental-evidence",
                "evidence-debate",
            ),
        },
        "financial": {
            "required": (
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
            ),
            "optional": (),
            "skills": (
                "a-share-filing-evidence",
                "fundamental-evidence",
                "earnings-quality",
                "financial-drivers",
                "evidence-debate",
            ),
        },
        "quality_review": {
            "required": (
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "company_information",
                "event_timeline",
            ),
            "optional": (),
            "skills": (
                "quality-review",
                "a-share-filing-evidence",
            ),
        },
        "valuation_review": {
            "required": (
                "market",
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
                "peer_comparison",
            ),
            "optional": (),
            "skills": (
                "a-share-filing-evidence",
                "fundamental-evidence",
                "earnings-quality",
                "financial-drivers",
                "evidence-debate",
            ),
        },
        "shareholder": {
            "required": ("shareholder_structure",),
            "optional": (),
            "skills": ("shareholder-structure", "evidence-debate"),
        },
        "business": {
            "required": ("business_structure",),
            "optional": (),
            "skills": ("business-structure",),
        },
        "business_growth": {
            "required": (
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
                "business_structure",
                "company_information",
                "event_timeline",
            ),
            "optional": (),
            "skills": (
                "a-share-filing-evidence",
                "earnings-quality",
                "financial-drivers",
                "business-structure",
            ),
        },
        "expectations": {
            "required": ("market", "analyst_expectations", "fundamentals"),
            "optional": ("company_information",),
            "skills": (
                "analyst-expectations",
                "fundamental-evidence",
                "evidence-debate",
            ),
        },
        "events": {
            "required": ("market", "company_information", "event_timeline"),
            "optional": ("fundamentals",),
            "skills": (
                "a-share-information",
                "event-timeline",
                "evidence-debate",
            ),
        },
        "valuation": {
            "required": ("market", "fundamentals", "peer_comparison"),
            "optional": ("analyst_expectations", "business_structure"),
            "skills": (
                "fundamental-evidence",
                "analyst-expectations",
                "business-structure",
                "evidence-debate",
            ),
        },
    }

    _FULL_MODULES = tuple(MODULE_LABELS)
    _FULL_SKILLS = (
        "a-share-information",
        "a-share-filing-evidence",
        "business-structure",
        "shareholder-structure",
        "analyst-expectations",
        "event-timeline",
        "fundamental-evidence",
        "earnings-quality",
        "financial-drivers",
        "evidence-debate",
        "conditional-outlook",
    )

    # Modules with a reporting-period or slowly changing basis may reuse a
    # recent saved evidence block. Price, quote and current information always
    # refresh for a live user question.
    MODULE_MAX_AGE_HOURS = {
        "market": 0,
        "company_information": 0,
        "fundamentals": 0,
        "earnings_quality": 168,
        "financial_drivers": 168,
        "business_structure": 168,
        "shareholder_structure": 24,
        "analyst_expectations": 24,
        "event_timeline": 6,
        "peer_comparison": 168,
        "outlook_calibration": 168,
    }

    def build(
        self,
        message: str,
        *,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        question = str(message or "").strip()
        history = conversation_history or []
        contextual_followup = self._is_focus_inheriting_followup(question, history)
        effective_text = self._effective_text(question, history)
        matched = [
            (key, label)
            for key, label, terms in self._FOCUS_RULES
            if any(term.lower() in effective_text.lower() for term in terms)
        ]
        if self._analyst_word_is_style_only(effective_text):
            matched = [item for item in matched if item[0] != "expectations"]
        if self._explicitly_excludes_financial_focus(question) and any(
            key not in {"financial", "quality_review"} for key, _ in matched
        ):
            matched = [
                item
                for item in matched
                if item[0] not in {"financial", "quality_review"}
            ]
        if is_stock_price_move_question(effective_text) and not any(
            key == "price_cause" for key, _ in matched
        ):
            matched = [("price_cause", "行情涨跌原因"), *matched]
        if self._is_relative_industry_question(effective_text):
            relative_item = ("relative_industry", "相对行业表现")
            matched = [
                relative_item,
                *[
                    item
                    for item in matched
                    if item[0] not in {"relative_industry", "price_action"}
                ],
            ]
        if any(key == "valuation_review" for key, _ in matched):
            # “估值约束候选”本身自然包含估值、财务、盈利、现金流、负债、
            # 同行和主营等词。这些维度已经由专项证据链覆盖，不应因此退化
            # 为 mixed。只有用户同时明确追问股价原因、股东或额外事件时，
            # 才在专项之外保留相应焦点。
            explicit_extra_focuses: set[str] = set()
            lowered = effective_text.lower()
            for key in (
                "price_cause",
                "price_action",
                "shareholder",
                "events",
            ):
                terms = next(
                    rule_terms
                    for rule_key, _, rule_terms in self._FOCUS_RULES
                    if rule_key == key
                )
                if any(term.lower() in lowered for term in terms):
                    explicit_extra_focuses.add(key)
            if self._explicitly_excludes_price_focus(effective_text):
                explicit_extra_focuses.difference_update(
                    {"price_cause", "price_action"}
                )
            if self._analyst_word_is_style_only(effective_text):
                explicit_extra_focuses.discard("expectations")
            matched = [
                item
                for item in matched
                if item[0] == "valuation_review" or item[0] in explicit_extra_focuses
            ]
        if any(key == "quality_review" for key, _ in matched):
            # “经营改善候选”本身会自然带出财务、利润、主营和同报告期等词。
            # 这些维度已经包含在专项证据链中，不能因此退化成 mixed 或额外加载
            # 同行估值、技术行情与分析师预期。只有用户明确另问估值、股价、股东
            # 或机构预期时，才保留相应的额外焦点。
            explicit_extra_focuses: set[str] = set()
            lowered = effective_text.lower()
            if any(
                term in lowered
                for term in (
                    "估值",
                    "市盈率",
                    "市净率",
                    "pe",
                    "pb",
                    "贵不贵",
                    "低估",
                )
            ):
                explicit_extra_focuses.add("valuation")
            for key in (
                "price_cause",
                "price_action",
                "shareholder",
                "expectations",
            ):
                terms = next(
                    rule_terms
                    for rule_key, _, rule_terms in self._FOCUS_RULES
                    if rule_key == key
                )
                if any(term.lower() in lowered for term in terms):
                    explicit_extra_focuses.add(key)
            if self._explicitly_excludes_price_focus(effective_text):
                explicit_extra_focuses.difference_update(
                    {"price_cause", "price_action"}
                )
            if self._analyst_word_is_style_only(effective_text):
                explicit_extra_focuses.discard("expectations")
            matched = [
                item
                for item in matched
                if item[0] == "quality_review" or item[0] in explicit_extra_focuses
            ]
        if any(key == "business_growth" for key, _ in matched):
            # “增长靠什么、第二增长曲线”自然会同时出现财报、收入、利润、
            # 主营和占比等词。专项计划已经把总量财务、分部结构和公司原文放在
            # 同一证据链里，不应退化成 mixed，更不能因此加载行情。
            matched = [item for item in matched if item[0] == "business_growth"]
        if any(key == "business" for key, _ in matched):
            # “先不谈涨跌”“不要给股价和技术指标”是在明确切换到主营，
            # 不能因为否定句里出现涨跌、股价或技术字样又把本轮拉回行情。
            if self._explicitly_excludes_price_focus(effective_text):
                matched = [
                    item
                    for item in matched
                    if item[0] not in {"price_cause", "price_action"}
                ]
            # 分部收入、占比和分部毛利率本来就是主营结构字段。“毛利”
            # 这个词本身不应额外加载整套财报、现金流和估值；只有用户明确
            # 同时询问净利润、现金流、负债等报表问题时才保留 financial。
            if not self._business_question_requests_financials(question):
                matched = [item for item in matched if item[0] != "financial"]
        if any(key == "price_cause" for key, _ in matched):
            matched = [item for item in matched if item[0] != "price_action"]
        comprehensive = any(
            term in effective_text
            for term in (
                "全面分析",
                "综合分析",
                "完整分析",
                "深度分析",
                "六维",
                "证据覆盖",
            )
        )

        has_price_cause = any(key == "price_cause" for key, _ in matched)
        if (comprehensive and not has_price_cause) or not matched:
            focus = "comprehensive"
            focus_label = "综合个股研究"
            required = list(self._FULL_MODULES)
            optional: list[str] = []
            skills = list(self._FULL_SKILLS)
        else:
            focus_keys = [item[0] for item in matched]
            focus = focus_keys[0] if len(focus_keys) == 1 else "mixed"
            focus_label = "、".join(item[1] for item in matched[:3])
            required = []
            optional = []
            skills = []
            for key in focus_keys:
                config = self._FOCUS_MODULES[key]
                self._extend_unique(required, config["required"])
                self._extend_unique(optional, config["optional"])
                self._extend_unique(skills, config["skills"])
            if "price_cause" in focus_keys and is_deep_stock_price_move_question(
                effective_text
            ):
                # Deep causal analysis should be informative without reviving
                # the generic full-report path. Add only structured reporting-
                # period evidence, which the prompt keeps separate from the
                # target day's direct price driver.
                self._extend_unique(
                    required,
                    ("fundamentals", "earnings_quality", "financial_drivers"),
                )
                self._extend_unique(
                    skills,
                    (
                        "a-share-filing-evidence",
                        "fundamental-evidence",
                        "earnings-quality",
                        "financial-drivers",
                    ),
                )
            if "price_cause" in focus_keys:
                skills = [skill for skill in skills if skill != "evidence-debate"]
            if "price_action" in focus_keys and any(
                term in effective_text
                for term in (
                    "后续",
                    "未来",
                    "走势",
                    "展望",
                    "情景",
                    "支撑",
                    "阻力",
                    "怎么看",
                )
            ):
                self._extend_unique(optional, ("outlook_calibration",))
                self._extend_unique(skills, ("conditional-outlook",))
            optional = [item for item in optional if item not in required]

        if self._explicitly_excludes_price_focus(effective_text):
            required = [item for item in required if item != "market"]
            optional = [item for item in optional if item != "market"]

        primary_focus = "price_cause" if has_price_cause else focus
        if contextual_followup and primary_focus == "price_cause":
            # A conversational request such as “那你现在最有把握能确认什么”
            # is asking for a tighter continuation of the prior price-cause
            # analysis.  The prior question may have requested financial and
            # event support, so keep those scoped modules while exposing the
            # actual conversational focus instead of relabelling the turn as a
            # generic mixed/comprehensive stock report.
            focus = "price_cause"
            focus_label = "行情涨跌原因追问"
            # The current evidence packet already carries the compact
            # reporting-period facts selected by the prior deep question.
            # Re-loading four long financial Skills makes a short continuation
            # slower and more report-like without adding facts. Keep only the
            # price/event reasoning Skills; the evidence-path Skill is appended
            # separately by the stock evidence service.
            skills = [
                skill
                for skill in skills
                if skill in {"a-share-information", "event-timeline"}
            ]

        selected_modules = [*required, *optional]
        module_labels = {key: self.MODULE_LABELS[key] for key in selected_modules}
        if focus == "relative_industry" and "analyst_expectations" in module_labels:
            module_labels["analyst_expectations"] = "所属行业指数与成分"
        labels = [module_labels[item] for item in selected_modules]
        answer_requirements = [
            "直接回答本轮问题，不机械重述全景报告",
            "至少保留一项反方证据或明确证据缺口",
            "价格、财务和事件必须保留各自时间口径",
        ]
        if has_price_cause:
            answer_requirements[1] = (
                "区分同日价格表现、基本面背景和仍未确认的直接驱动"
            )
        return {
            "contract_version": self.CONTRACT_VERSION,
            "focus": focus,
            "primary_focus": primary_focus,
            "focus_label": focus_label,
            "question": question,
            "effective_question": effective_text,
            "contextual_followup": contextual_followup,
            "required_modules": required,
            "optional_modules": optional,
            "selected_modules": selected_modules,
            "selected_skills": skills,
            "module_labels": module_labels,
            "module_max_age_hours": {
                key: self.MODULE_MAX_AGE_HOURS[key] for key in selected_modules
            },
            "progress_label": "正在核验"
            + "、".join(labels[:4])
            + ("等证据…" if len(labels) > 4 else "…"),
            "answer_requirements": answer_requirements,
        }

    @classmethod
    def _effective_text(
        cls,
        question: str,
        history: list[dict[str, Any]],
    ) -> str:
        if cls._is_focus_inheriting_followup(question, history):
            previous_user_questions = [
                str(item.get("content") or "").strip()
                for item in history
                if item.get("role") == "user"
                and str(item.get("content") or "").strip()
            ]
            previous_focus_question = next(
                (
                    item
                    for item in reversed(previous_user_questions)
                    if cls._has_explicit_focus(item)
                ),
                previous_user_questions[-1] if previous_user_questions else "",
            )
            if previous_focus_question:
                return f"{previous_focus_question} {question}".strip()
        has_explicit_focus = cls._has_explicit_focus(question)
        if has_explicit_focus or len(question) > 18:
            return question
        previous_user_questions = [
            str(item.get("content") or "").strip()
            for item in history
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ][-2:]
        return " ".join([*previous_user_questions, question]).strip()

    @classmethod
    def _has_explicit_focus(cls, question: str) -> bool:
        lowered = question.lower()
        return cls._is_relative_industry_question(question) or any(
            term.lower() in lowered
            for _, _, terms in cls._FOCUS_RULES
            for term in terms
        )

    @staticmethod
    def _explicitly_excludes_price_focus(question: str) -> bool:
        folded = re.sub(r"\s+", "", str(question or "")).casefold()
        return any(
            phrase in folded
            for phrase in (
                "先不谈涨跌",
                "不谈涨跌",
                "先不谈股价",
                "不谈股价",
                "不要给股价",
                "不给股价",
                "不要写股价",
                "不要谈股价",
                "不要股价",
                "不要给技术指标",
                "不给技术指标",
                "不要写技术指标",
                "不要谈技术指标",
                "不要技术指标",
                "不看技术指标",
                "先不谈行情",
                "不谈行情",
            )
        )

    @staticmethod
    def _explicitly_excludes_financial_focus(question: str) -> bool:
        folded = re.sub(r"\s+", "", str(question or "")).casefold()
        return any(
            phrase in folded
            for phrase in (
                "先不谈财报",
                "不谈财报了",
                "先不谈财务",
                "不谈财务了",
                "不要重复财报",
                "别重复财报",
                "不要重复刚才的财务",
                "别重复刚才的财务",
                "不要再讲财务",
                "别再讲财务",
            )
        )

    @staticmethod
    def _analyst_word_is_style_only(question: str) -> bool:
        folded = re.sub(r"\s+", "", str(question or "")).casefold()
        if "分析师" not in folded:
            return False
        explicit_expectation_terms = (
            "分析师预期",
            "分析师一致预期",
            "一致预期",
            "研报",
            "评级",
            "eps",
            "机构预期",
            "预期修订",
            "上修",
            "下修",
        )
        if any(term in folded for term in explicit_expectation_terms):
            return False
        return bool(
            re.search(
                r"(?:像|按|用)(?:一个)?分析师(?:一样|的方式|的口吻)?"
                r"(?:和我)?(?:聊天|说|讲|写|解释|分析)",
                folded,
            )
        )

    @staticmethod
    def _business_question_requests_financials(question: str) -> bool:
        folded = re.sub(r"\s+", "", str(question or "")).casefold()
        return any(
            term in folded
            for term in (
                "净利润",
                "归母",
                "扣非",
                "经营现金流",
                "现金流",
                "资产负债率",
                "负债",
                "应收",
                "存货",
                "财务费用",
                "销售费用",
                "管理费用",
                "研发费用",
                "利润表",
                "资产负债表",
                "现金流量表",
                "财报质量",
            )
        )

    @classmethod
    def _is_focus_inheriting_followup(
        cls,
        question: str,
        history: list[dict[str, Any]],
    ) -> bool:
        if not history:
            return False
        folded = re.sub(r"\s+", "", str(question or "")).casefold()
        if not folded:
            return False
        if any(
            term in folded
            for term in (
                "先不谈",
                "不谈财报了",
                "不谈财务了",
                "换个话题",
                "换个问题",
                "转到股东",
                "接着看股东",
            )
        ):
            return False
        if any(
            term in folded
            for term in (
                "你刚才",
                "你上段",
                "上一段",
                "上个回答",
                "刚才那段",
                "刚才说了很多",
                "上一问",
                "上一题",
                "重答",
                "重新回答",
                "真正值得我改变判断",
                "哪些只是会计口径",
                "哪些只是短期节奏",
                "别重复整份",
                "不要重复整份",
            )
        ):
            return True
        if cls._has_explicit_focus(question):
            return False
        return any(
            term in folded
            for term in (
                "那",
                "那么",
                "刚才",
                "前面",
                "上一轮",
                "上一问",
                "继续",
                "接着",
                "这些",
                "上述",
                "不要重复",
                "别重复",
                "像继续聊天",
                "最有把握",
                "最不能确认",
                "能确认什么",
                "不能确认什么",
                "换句话说",
                "这意味着什么",
            )
        )

    @staticmethod
    def _is_relative_industry_question(text: str) -> bool:
        folded = re.sub(r"\s+", "", str(text or "")).casefold()
        return bool(
            re.search(r"相对[^，。；,]{0,12}(?:行业|板块)", folded)
            or re.search(r"相对[^，。；,]{0,12}(?:cs|中证)[^，。；,]{0,8}指数", folded)
            or any(
                term in folded
                for term in (
                    "行业增强",
                    "行业走弱",
                    "跑赢行业",
                    "跑输行业",
                    "超额收益",
                )
            )
        )

    @staticmethod
    def _extend_unique(target: list[str], values: Any) -> None:
        for value in values:
            if value not in target:
                target.append(value)
