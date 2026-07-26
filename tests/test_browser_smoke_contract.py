from __future__ import annotations

from pathlib import Path


RUNNER = Path(__file__).parents[1] / "scripts" / "browser_smoke.py"


def test_browser_smoke_runner_covers_desktop_mobile_and_core_routes() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    for fragment in (
        'Viewport("desktop", 1280, 720)',
        'Viewport("mobile-390", 390, 844)',
        '"/today"',
        '"/research?mode=screening"',
        '"/stocks/000063.SZ?tab=overview"',
        '"/stocks/000063.SZ?tab=history"',
        '"/reviews?tab=trades"',
        '"/research/new"',
        "hasHorizontalOverflow",
        "stock_overview_mobile_widths",
        "screening_section_state",
        'data-load-state="ready"',
        "strategy_ready_seconds",
        'page.locator(\'[data-screening-jump="li_zong"]\').click()',
        'page.locator(\'[data-screening-jump="general"]\').click()',
        "透明选股默认分区异常",
        "透明选股切换异常",
        "透明选股返回异常",
        "390px 核心卡片不可读",
        "console_errors",
        "failed_responses",
        "page.screenshot",
    ):
        assert fragment in source


def test_browser_smoke_runner_is_read_only() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    for fragment in (
        'method="POST"',
        'method="PUT"',
        'method="PATCH"',
        'method="DELETE"',
        "page.request.post(",
        "page.request.put(",
        "page.request.patch(",
        "page.request.delete(",
    ):
        assert fragment not in source

    assert source.count(".click()") == 2
    assert 'page.locator(\'[data-screening-jump="li_zong"]\').click()' in source
    assert 'page.locator(\'[data-screening-jump="general"]\').click()' in source
