from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.static_assets import STATIC_ASSET_MEDIA_TYPES


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_demo_loads_only_registered_local_assets() -> None:
    html = (STATIC / "demo.html").read_text(encoding="utf-8")
    sources = set(re.findall(r'<script src="/static/([^"]+)"', html))
    styles = set(re.findall(r'<link rel="stylesheet" href="/static/([^"]+)"', html))

    assert sources | styles == set(STATIC_ASSET_MEDIA_TYPES)
    assert "<style>" not in html
    assert "<script>" not in html


def test_frontend_business_modules_stay_bounded() -> None:
    for name, media_type in STATIC_ASSET_MEDIA_TYPES.items():
        path = STATIC / name
        assert path.exists(), name
        if media_type == "application/javascript":
            assert len(path.read_text(encoding="utf-8").splitlines()) <= 1000, name


def test_market_diagnosis_keeps_agent_and_live_dates_separate() -> None:
    source = (STATIC / "qs-market.js").read_text(encoding="utf-8")

    assert "Agent 本轮分析交易日" in source
    assert "最新分钟行情至" in source
    assert "未并入本轮回答" in source
    assert "已分离，避免混用" in source


def test_mobile_navigation_scrolls_active_page_into_view() -> None:
    workspace = (STATIC / "qs-workspace.js").read_text(encoding="utf-8")
    page = (STATIC / "demo.html").read_text(encoding="utf-8")
    styles = (STATIC / "demo.css").read_text(encoding="utf-8")

    assert 'window.matchMedia("(max-width: 600px)").matches' in workspace
    assert "centeredLeft" in workspace
    assert "mobileNavigation.scrollLeft" in workspace
    assert "scrollbar-width: none" in styles
    assert page.count('class="nav-item') == 7
    assert 'data-page="screening" aria-label="透明选股"' in page
    assert 'data-page="agent" aria-label="金融顾问"' in page
    assert "grid-template-columns: repeat(3,minmax(0,1fr))" in styles


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_frontend_javascript_modules_parse() -> None:
    for name, media_type in STATIC_ASSET_MEDIA_TYPES.items():
        if media_type != "application/javascript":
            continue
        subprocess.run(
            ["node", "--check", str(STATIC / name)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
