from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
HTML = (ROOT / "app/static/high-fidelity-demo.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/high-fidelity-demo.css").read_text(encoding="utf-8")
JS = (ROOT / "app/static/high-fidelity-demo.js").read_text(encoding="utf-8")


def test_ai_page_has_two_independent_skill_workspaces():
    assert 'class="skill-workspace-grid"' in HTML
    assert 'id="laoLiTarget"' in HTML
    assert 'id="laoLiQuestion"' in HTML
    assert 'id="startLaoLiDiagnosis"' in HTML
    assert 'id="laoLiAnswer"' in HTML
    assert 'id="fiveDimTarget"' in HTML
    assert 'id="fiveDimFocus"' in HTML
    assert 'id="startFiveDimension"' in HTML
    assert 'id="fiveDimensionList"' in HTML
    assert "老李诊股" in HTML
    assert "五维分析" in HTML


def test_ai_workspaces_use_separate_state_and_endpoints():
    assert "var laoLiState=" in JS
    assert "var fiveDimensionState=" in JS
    assert "researchState" not in JS
    assert "runLaoLiDiagnosis" in JS
    assert "runFiveDimensionAnalysis" in JS
    assert "researchRequest('/me/ai-research/runs'" in JS
    assert (
        "researchRequest('/me/ai-research/five-dimension-runs'"
        in JS
    )
    assert "fiveDimTarget" in JS
    assert "laoLiTarget" in JS


def test_five_dimension_workspace_exposes_v7_labels_not_private_prompts():
    for label in ("基本面", "行业面", "估值面", "技术面", "风险面"):
        assert label in HTML or label in JS
    assert "v7.0.0" in HTML
    assert "板块主线资格 → 个股八项硬筛选" not in HTML
    assert "COMMON_RUNTIME_STANDARD" not in HTML


def test_ai_workspace_typography_and_responsive_layout_are_readable():
    assert ".skill-workspace-grid" in CSS
    assert ".skill-result-copy" in CSS
    assert "font-size:16px" in CSS
    assert "line-height:1.75" in CSS
    assert "@media(max-width:820px)" in CSS
    assert ".skill-workspace-grid{grid-template-columns:1fr}" in CSS
