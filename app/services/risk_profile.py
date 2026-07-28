from __future__ import annotations

from typing import Any


QUESTIONNAIRE = [
    {
        "key": "fund_use_horizon",
        "label": "这笔资金预计什么时候可能要用？",
        "help": "时间越短，越不能承受净值在需要用钱时仍未恢复。",
        "options": [
            {"value": "short", "label": "近期可能要用"},
            {"value": "medium", "label": "一段时间内不用"},
            {"value": "long", "label": "长期不用"},
        ],
    },
    {
        "key": "liquidity_need",
        "label": "你对随时取用这笔钱的要求？",
        "help": "流动性要求高时，应优先排除赎回慢、波动大或成交不活跃的产品。",
        "options": [
            {"value": "high", "label": "随时可能需要"},
            {"value": "medium", "label": "可以等待到账"},
            {"value": "low", "label": "通常不会临时动用"},
        ],
    },
    {
        "key": "loss_tolerance",
        "label": "如果账户出现明显亏损，你更接近哪种反应？",
        "help": "这里问的是实际行为承受力，不是希望获得多高收益。",
        "options": [
            {"value": "low", "label": "很难接受，会影响生活或睡眠"},
            {"value": "medium", "label": "会不安，但能先核验原因"},
            {"value": "high", "label": "能接受较大波动并按计划复核"},
        ],
    },
    {
        "key": "emergency_reserve",
        "label": "是否已经单独留有应急资金？",
        "help": "应急资金不足时，不应把生活备用金当作长期投资资金。",
        "options": [
            {"value": "none", "label": "没有单独准备"},
            {"value": "partial", "label": "有一些，但不确定是否够"},
            {"value": "adequate", "label": "已单独准备"},
        ],
    },
    {
        "key": "debt_burden",
        "label": "当前还款压力如何？",
        "help": "高成本或刚性负债会降低可以承担投资波动的空间。",
        "options": [
            {"value": "high", "label": "压力明显"},
            {"value": "medium", "label": "有负债但可正常承担"},
            {"value": "low", "label": "负债压力较小"},
            {"value": "none", "label": "没有负债"},
        ],
    },
    {
        "key": "investment_experience",
        "label": "你对基金、ETF和净值波动的实际经验？",
        "help": "经验不能提高承受能力，但会影响产品复杂度和解释方式。",
        "options": [
            {"value": "beginner", "label": "刚开始了解"},
            {"value": "some", "label": "买过并经历过波动"},
            {"value": "experienced", "label": "能理解净值、回撤和产品规则"},
        ],
    },
    {
        "key": "primary_objective",
        "label": "这笔钱最主要想解决什么？",
        "help": "目标决定先看确定性、现金流安排，还是长期增长。",
        "options": [
            {"value": "preservation", "label": "优先保持稳定和可用"},
            {"value": "balanced", "label": "在波动与增长之间平衡"},
            {"value": "growth", "label": "接受波动争取长期增长"},
        ],
    },
]


_OPTION_LABELS = {
    question["key"]: {
        option["value"]: option["label"] for option in question["options"]
    }
    for question in QUESTIONNAIRE
}


class RiskProfileService:
    """User-confirmed suitability facts; chat never writes these implicitly."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def get_packet(self, user_id: str) -> dict[str, Any]:
        return {
            "questionnaire_version": "qingshu_suitability_v1",
            "questions": QUESTIONNAIRE,
            "draft": self.database.latest_risk_profile(user_id, status="draft"),
            "confirmed": self.database.latest_risk_profile(
                user_id, status="confirmed"
            ),
            "boundary": (
                "问卷答案只有在你点击确认后才会用于AI适合性回答；聊天内容不会自动改写正式画像。"
            ),
        }

    def save_draft(
        self,
        user_id: str,
        *,
        answers: dict[str, str],
        base_version: int,
    ) -> dict[str, Any]:
        normalized = self._validate_answers(answers)
        derived = self._derive(normalized)
        return self.database.save_risk_profile_draft(
            user_id,
            answers=normalized,
            derived=derived,
            base_version=base_version,
        )

    def confirm(
        self,
        user_id: str,
        *,
        version_no: int,
    ) -> dict[str, Any]:
        confirmed = self.database.confirm_risk_profile(user_id, version_no)
        if confirmed is None:
            raise LookupError("待确认风险画像不存在或版本已经变化")
        return confirmed

    def confirmed_context(self, user_id: str) -> dict[str, Any] | None:
        profile = self.database.latest_risk_profile(user_id, status="confirmed")
        if profile is None:
            return None
        answers = profile.get("answers") or {}
        return {
            "version_no": profile.get("version_no"),
            "confirmed_at": profile.get("confirmed_at"),
            "answer_labels": {
                key: _OPTION_LABELS.get(key, {}).get(value, value)
                for key, value in answers.items()
            },
            "derived": profile.get("derived") or {},
            "boundary": (
                "这些事实来自用户已确认问卷；只能辅助解释选择条件，不能替代持牌适当性评估。"
            ),
        }

    @staticmethod
    def _validate_answers(answers: dict[str, str]) -> dict[str, str]:
        if not isinstance(answers, dict):
            raise ValueError("风险问卷答案格式不正确")
        expected = {question["key"] for question in QUESTIONNAIRE}
        missing = expected - set(answers)
        extra = set(answers) - expected
        if missing or extra:
            raise ValueError("请完整回答当前版本的全部风险问卷")
        normalized: dict[str, str] = {}
        for key in expected:
            value = str(answers.get(key) or "").strip()
            if value not in _OPTION_LABELS[key]:
                raise ValueError("风险问卷包含未知选项，请重新选择")
            normalized[key] = value
        return normalized

    @staticmethod
    def _derive(answers: dict[str, str]) -> dict[str, Any]:
        scores = {
            "fund_use_horizon": {"short": 0, "medium": 1, "long": 2},
            "liquidity_need": {"high": 0, "medium": 1, "low": 2},
            "loss_tolerance": {"low": 0, "medium": 1, "high": 2},
            "emergency_reserve": {"none": 0, "partial": 1, "adequate": 2},
            "debt_burden": {"high": 0, "medium": 1, "low": 2, "none": 2},
            "investment_experience": {"beginner": 0, "some": 1, "experienced": 2},
            "primary_objective": {"preservation": 0, "balanced": 1, "growth": 2},
        }
        score = sum(scores[key][value] for key, value in answers.items())
        if score <= 4:
            capacity = "cautious"
            label = "当前更需要优先保护流动性和生活安排"
        elif score <= 9:
            capacity = "balanced"
            label = "当前需要在流动性、波动和长期目标之间平衡"
        else:
            capacity = "growth"
            label = "当前具备研究较高波动产品的部分条件"
        constraints: list[str] = []
        if answers["emergency_reserve"] != "adequate":
            constraints.append("应急资金仍需单独核对")
        if answers["debt_burden"] == "high":
            constraints.append("还款压力会降低可承担波动的空间")
        if answers["fund_use_horizon"] == "short":
            constraints.append("资金近期可能使用，期限错配风险较高")
        if answers["liquidity_need"] == "high":
            constraints.append("需要优先核对到账速度和交易流动性")
        if answers["investment_experience"] == "beginner":
            constraints.append("产品结构和费用规则需要用通俗语言解释")
        return {
            "risk_capacity_band": capacity,
            "summary_label": label,
            "constraints": constraints,
            "method": (
                "七项用户自报事实的确定性摘要；不使用年龄、收入猜测或市场预测。"
            ),
            "not_a_recommendation": True,
        }


__all__ = ["QUESTIONNAIRE", "RiskProfileService"]
