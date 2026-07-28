from __future__ import annotations

from typing import Any


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
            "shareholder",
            "股东与持有人变化",
            ("股东", "户数", "十大股东", "持有人", "筹码", "人均持股"),
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
                "同报告期",
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
                "今天表现",
                "今日表现",
                "今天怎么样",
                "今日怎么样",
            ),
        ),
    )

    _FOCUS_MODULES = {
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
                "company_information",
                "event_timeline",
            ),
            "optional": ("outlook_calibration",),
            "skills": (
                "a-share-information",
                "event-timeline",
                "fundamental-evidence",
                "evidence-debate",
                "conditional-outlook",
            ),
        },
        "financial": {
            "required": (
                "market",
                "fundamentals",
                "earnings_quality",
                "financial_drivers",
            ),
            "optional": ("company_information", "event_timeline"),
            "skills": (
                "a-share-filing-evidence",
                "fundamental-evidence",
                "earnings-quality",
                "financial-drivers",
                "evidence-debate",
            ),
        },
        "shareholder": {
            "required": ("market", "shareholder_structure"),
            "optional": ("company_information", "event_timeline"),
            "skills": ("shareholder-structure", "evidence-debate"),
        },
        "business": {
            "required": ("market", "business_structure", "fundamentals"),
            "optional": ("company_information",),
            "skills": (
                "business-structure",
                "fundamental-evidence",
                "evidence-debate",
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
        effective_text = self._effective_text(question, conversation_history or [])
        matched = [
            (key, label)
            for key, label, terms in self._FOCUS_RULES
            if any(term.lower() in effective_text.lower() for term in terms)
        ]
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

        if comprehensive or not matched:
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
            optional = [item for item in optional if item not in required]

        selected_modules = [*required, *optional]
        labels = [self.MODULE_LABELS[item] for item in selected_modules]
        return {
            "contract_version": self.CONTRACT_VERSION,
            "focus": focus,
            "focus_label": focus_label,
            "question": question,
            "effective_question": effective_text,
            "required_modules": required,
            "optional_modules": optional,
            "selected_modules": selected_modules,
            "selected_skills": skills,
            "module_labels": {key: self.MODULE_LABELS[key] for key in selected_modules},
            "module_max_age_hours": {
                key: self.MODULE_MAX_AGE_HOURS[key] for key in selected_modules
            },
            "progress_label": "正在核验"
            + "、".join(labels[:4])
            + ("等证据…" if len(labels) > 4 else "…"),
            "answer_requirements": [
                "直接回答本轮问题，不机械重述全景报告",
                "至少保留一项反方证据或明确证据缺口",
                "价格、财务和事件必须保留各自时间口径",
            ],
        }

    @classmethod
    def _effective_text(
        cls,
        question: str,
        history: list[dict[str, Any]],
    ) -> str:
        lowered = question.lower()
        has_explicit_focus = any(
            term.lower() in lowered
            for _, _, terms in cls._FOCUS_RULES
            for term in terms
        )
        if has_explicit_focus or len(question) > 18:
            return question
        previous_user_questions = [
            str(item.get("content") or "").strip()
            for item in history
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ][-2:]
        return " ".join([*previous_user_questions, question]).strip()

    @staticmethod
    def _extend_unique(target: list[str], values: Any) -> None:
        for value in values:
            if value not in target:
                target.append(value)
