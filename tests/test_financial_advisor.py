from app.services.agent_financial_advisor import normalize_financial_advisor_answer


def test_incomplete_suitability_answer_removes_invented_chinese_thresholds() -> None:
    evidence = {
        "type": "general_research",
        "financial_advisor_context": {"status": "needs_profile"},
    }
    answer = (
        "股票基金短期可能下跌百分之二三十甚至更多。"
        "市场不好时可能一段时间跌掉二三成甚至更多。"
        "如果这笔钱三五年内必须用到，应先核对流动性；"
        "如果十年都用不上，可以按长期资金理解。"
        "买入后暂时亏了两三成时，也要判断是否会被迫卖出。"
        "先留几个月生活费。"
    )

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "百分之二三十" not in normalized
    assert "三五年内" not in normalized
    assert "十年都用不上" not in normalized
    assert "两三成" not in normalized
    assert "几个月生活费" not in normalized
    assert "短期可能出现明显下跌" in normalized
    assert "市场不好时可能出现明显下跌" in normalized
    assert "短期内" in normalized
    assert "长期不用" in normalized
    assert "明显账面亏损" in normalized
    assert "必要的应急生活费" in normalized


def test_suitability_answer_removes_redundant_threshold_example() -> None:
    evidence = {
        "financial_advisor_context": {"status": "needs_profile"},
    }
    answer = "如果投资后三五年内账面亏损了，比如亏了两三成，你会卖吗？"

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert normalized == "如果投资后出现明显账面亏损，你会卖吗？"


def test_suitability_answer_normalizes_real_beginner_response_artifacts() -> None:
    evidence = {
        "financial_advisor_context": {"status": "needs_profile"},
    }
    answer = (
        "如果是半年内要用的钱，应优先考虑流动性；"
        "如果是五年以上用不到的钱，才可能承担更大波动。"
        "你需要先搞清两件事：这笔钱什么时候会用到，以及能否接受波动。"
        "请先告诉我这两点，我再帮你梳理。"
    )

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "半年" not in normalized
    assert "五年以上" not in normalized
    assert "两件事" not in normalized
    assert "这两点" not in normalized
    assert "短期内要用的钱" in normalized
    assert "长期不用的钱" in normalized
    assert "如果继续细化，可以先补充：" in normalized
    assert "请先告诉我这些情况" in normalized


def test_suitability_answer_preserves_question_when_numeric_example_is_removed() -> (
    None
):
    evidence = {
        "financial_advisor_context": {"status": "needs_profile"},
    }
    answer = (
        "如果是短期内必须花的钱，那就只能选波动很小的货币基金、存款这类；"
        "如果是三年长期不用的闲钱，才有空间考虑波动更大的类型。"
        "为了给你更贴切的分析，请你先告诉我两点：\n"
        "- 你这笔钱大概什么时候一定要用？\n"
        "- 如果投入后暂时亏掉一部分，你能承受的程度是怎样的？"
        "（比如“一分都不能亏”“亏5%可以，再多就心慌”）"
    )

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "三年" not in normalized
    assert "5%" not in normalized
    assert "告诉我两点" not in normalized
    assert "只能选" not in normalized
    assert "长期不用的闲钱" in normalized
    assert "安全性和流动性更高的工具" in normalized
    assert "你能承受的程度是怎样的" in normalized
    assert "能否承受明显波动" in normalized


def test_suitability_answer_normalizes_duration_list_and_percentage_spacing() -> None:
    evidence = {
        "financial_advisor_context": {"status": "needs_profile"},
    }
    answer = (
        "这笔钱大概多久后要用（几个月、一两年，还是可以放长期）。"
        "你能接受账户上暂时亏多少而不慌张"
        "（例如，跌 5% 受不了，还是跌 10% 还能继续持有）。"
    )

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "几个月" not in normalized
    assert "一两年" not in normalized
    assert "5%" not in normalized
    assert "10%" not in normalized
    assert "短期内，还是可以长期不用" in normalized
    assert "出现明显下跌就受不了" in normalized
    assert "出现明显下跌仍能继续持有" in normalized


def test_non_suitability_answer_is_not_rewritten() -> None:
    answer = "债券久期越长，通常对利率变化越敏感。"

    assert (
        normalize_financial_advisor_answer(
            answer,
            {"type": "general_research"},
        )
        == answer
    )


def test_confirmed_suitability_answer_still_removes_invented_thresholds() -> None:
    answer = (
        "根据已确认画像，如果三年以上不用，可以关注宽基ETF；"
        "如果只能接受5%的亏损，就优先考虑低波动产品。"
    )
    evidence = {
        "financial_advisor_context": {
            "status": "ready_for_conditional_guidance",
            "confirmed_risk_profile": {"version_no": 1},
        }
    }

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "三年以上" not in normalized
    assert "5%" not in normalized
    assert "长期" in normalized
    assert "明显幅度" in normalized


def test_confirmed_suitability_answer_softens_overclaim_and_drops_dangling_prompt() -> (
    None
):
    answer = (
        "纯债基金可能是最适合您现在优先比较的方向。"
        "所以，优先从纯债基金开始比较，收益更高。"
        "所以我需要再确认两件事："
    )
    evidence = {
        "financial_advisor_context": {
            "status": "ready_for_conditional_guidance",
            "confirmed_risk_profile": {"version_no": 1},
        }
    }

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "最适合" not in normalized
    assert "收益更高" not in normalized
    assert "确认两件事" not in normalized
    assert "值得优先了解和比较的方向之一" in normalized
    assert "重点核对风险、流动性和完整成本" in normalized


def test_suitability_answer_repairs_concatenated_intro_and_duplicate_question() -> None:
    answer = (
        "现在还不能替你缩小范围，但你可以如果继续细化，可以先补充：\n\n"
        "1. 这笔钱什么时候可能会用？\n"
        "2. 如果账户出现亏损，你能否继续持有？"
        "（2. 如果账户出现亏损，你能否继续持有？"
    )
    evidence = {"financial_advisor_context": {"status": "needs_profile"}}

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "你可以如果" not in normalized
    assert normalized.count("2. 如果账户出现亏损") == 1
    assert "如果继续细化，可以先补充：" in normalized


def test_financial_advisor_keeps_evidence_backed_fund_returns() -> None:
    evidence = {
        "financial_advisor_context": {"status": "needs_profile"},
        "fund_product_context": {
            "comparison": {
                "products": [
                    {
                        "code": "510300",
                        "returns": {
                            "one_month_pct": -2.92,
                            "one_year_pct": 16.12,
                        },
                        "live_quote": {"pct_change": 1.11},
                    },
                    {
                        "code": "159915",
                        "returns": {
                            "one_month_pct": -14.14,
                            "one_year_pct": 55.97,
                        },
                    },
                ]
            }
        },
    }
    answer = (
        "510300近1月为-2.92%，近1年为16.12%；"
        "159915近1月为-14.14%，近1年为+55.97%。"
        "如果你亏损20%就受不了，还需要先核对真实承受力。"
    )

    normalized = normalize_financial_advisor_answer(answer, evidence)

    assert "-2.92%" in normalized
    assert "16.12%" in normalized
    assert "-14.14%" in normalized
    assert "+55.97%" in normalized
    assert "20%" not in normalized
    assert "近1年" in normalized
    assert "出现明显亏损就受不了" in normalized
