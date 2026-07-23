from pathlib import Path


DEMO_HTML = Path(__file__).parents[1] / "app" / "static" / "demo.html"


def test_demo_connects_action_plans_and_trade_reviews() -> None:
    page = DEMO_HTML.read_text(encoding="utf-8")

    for fragment in (
        'optionalApi(`/v1/stocks/${encoded}/action-plans`)',
        'api(`/v1/stocks/${encodeURIComponent(symbol)}/action-plans`',
        'api(`/v1/action-plans/${encodeURIComponent(plan.id)}`',
        'api(`/v1/action-plans/${encodeURIComponent(plan.id)}/transition`',
        'optionalApi(`/v1/stocks/${encoded}/trade-reviews`)',
        'api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/generate-draft`',
        'api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/draft`',
        'api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/confirm`',
        'api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/archive`',
        "function renderActionPlanWorkspace(symbol, plans, positionWorkspace)",
        "function renderTradeReviewWorkspace(symbol, reviews)",
        "renderActionPlanWorkspace(symbol, plans, positionWorkspace)",
        "renderTradeReviewWorkspace(currentSymbol, reviews)",
        '["saved", "partially_executed"].includes(item.status) && String(item.id) === String(preferredPlanId)',
        '["saved", "partially_executed"].includes(item.status) && item.action_type === type.value',
        'headers: {"Idempotency-Key": `action-plan-',
        'JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 0})',
        "系统只检查用户条件，不生成建议",
        "价格结果和逻辑结果分开呈现",
        "plan_id",
        "action_type",
        "trigger_text",
        "target_position_percent",
        "base_version",
    ):
        assert fragment in page


def test_demo_uses_only_supported_plan_and_review_statuses() -> None:
    page = DEMO_HTML.read_text(encoding="utf-8")

    for status in (
        "draft",
        "checked",
        "saved",
        "partially_executed",
        "executed",
        "cancelled",
        "expired",
        "waiting_data",
        "ready",
        "confirmed",
        "archived",
        "revised",
    ):
        assert status in page
    assert "awaiting_review" not in page
    assert "ai_draft" not in page
    assert "can_generate" not in page
