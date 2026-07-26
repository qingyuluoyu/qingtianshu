from pathlib import Path


HTML = Path("app/static/high-fidelity-demo.html").read_text(encoding="utf-8")
JS = Path("app/static/high-fidelity-demo.js").read_text(encoding="utf-8")
CSS = Path("app/static/high-fidelity-demo.css").read_text(encoding="utf-8")


def test_profile_html_contains_workbench_containers_without_fake_capabilities():
    for element_id in (
        "profileSummaryCards",
        "profileTodoList",
        "profileRecentResearch",
        "profileRecentWatchlist",
        "profileLifecycle",
        "profileDataTime",
    ):
        assert f'id="{element_id}"' in HTML
    for forbidden in (
        "尊享会员",
        "积分余额",
        "API 自建",
        "支付宝订单",
        "实名认证",
        "138*****5628",
    ):
        assert forbidden not in HTML


def test_profile_frontend_renders_workbench_and_removes_account_actions():
    assert "renderProfileWorkbench" in JS
    assert "data.workbench" in JS
    assert "profile-workbench-grid" in CSS
    for forbidden in (
        "/me/contact-phone",
        "/me/payment-orders/draft",
        "profileOrderDraft",
        "saveProfilePhone",
        "后端聚合接口",
    ):
        assert forbidden not in JS
