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
        '"/reviews?tab=market"',
        '"/account"',
        '"/research/new"',
        "hasHorizontalOverflow",
        "stock_overview_mobile_widths",
        "screening_section_state",
        "screening_candidate_disclosure_state",
        "agent_landing_state",
        "agent_quick_actions_state",
        'node.closest(".quick-action-group")?.hidden !== true',
        "agent_conversation_scope_state",
        "agent_stream_reading_state",
        "review_section_state",
        "populated_review_detail_state",
        "market_review_section_state",
        "market_overview_state",
        "account_section_state",
        "account_risk_profile_states",
        'data-load-state="ready"',
        "strategy_ready_seconds",
        'page.locator(\'[data-screening-jump="li_zong"]\').click()',
        'page.locator(\'[data-screening-jump="general"]\').click()',
        "透明选股默认分区异常",
        "透明选股切换异常",
        "透明选股返回异常",
        "条件选股候选没有保持三项核心指标与默认折叠",
        "条件选股完整数据或入选依据没有保留在展开区",
        "条件选股模板用途或逐股核验提示不可读",
        "390px 条件选股候选卡宽度不足",
        "通过后端守卫的流式正文没有显示",
        "后续进度事件覆盖了已显示的流式正文",
        "用户滚轮操作没有停止自动跟随",
        "最终回答到达后抢回了用户滚动位置",
        "已有安全流式正文仍被清空后逐段重放",
        "新建对话入口仍需滚动才能发现全部功能",
        "新建对话输入框和发送区超出当前视口",
        "对话首屏快捷能力仍被横向裁切",
        "全部工具不能展开隐藏的专项能力",
        "历史对话分类验收没有覆盖67条列表",
        "基金与ETF旧对话仍被错误归入个股",
        "退休理财旧对话仍被错误归入选股",
        "最近对话默认视图没有限制为8个主题并固定当前旧会话",
        "查看全部历史没有恢复67条完整对话",
        "历史搜索被最近对话限制截断，无法找到旧会话",
        "全部历史收起后没有回到最新对话顶部",
        "研究复盘标题仍使用英文或内部标签",
        "空交易复盘仍展示无效搜索筛选或双栏空状态",
        "没有交易记录时仍展示搜索和状态筛选",
        "空交易复盘没有提供唯一且直白的下一步",
        "空交易复盘没有解释真实的三步形成流程",
        "移动端复盘步骤仍被横向挤压，标题和说明无法正常阅读",
        "有记录复盘详情仍存在重复分区或内部式标题",
        "复盘价格事实没有合并成单一可读区域",
        "复盘价格计算口径没有默认折叠",
        "复盘详情仍展示内部字段名或未经证实的心理诊断",
        "市场复盘仍向普通用户展示内部版本规划",
        "市场复盘摘要仍未使用已保存的A股结构事实",
        "市场总览仍把个股报告或机会混入市场文章",
        "A股首屏摘要没有直接展示市场广度和成交事实",
        "A股市场明细仍混入重复的个人关注模块",
        "市场Agent入口标题不够直接",
        "390px 李总策略结果分类仍被横向隐藏",
        "服务、隐私与版本说明默认展开",
        "个人中心技术字段字号小于12px",
        "风险画像初始回答进度不正确",
        "风险画像缺失答案没有定位并聚焦第一道问题",
        "风险画像填写完成后没有明确引导保存核对",
        "风险画像草稿状态没有明确等待用户确认",
        "风险画像确认后缺少直达金融顾问入口",
        "风险画像确认后没有说明下一步用途",
        "风险画像三步流程在当前视口排版异常",
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

    assert source.count(".click()") == 4
    assert 'page.locator(\'[data-screening-jump="li_zong"]\').click()' in source
    assert 'page.locator(\'[data-screening-jump="general"]\').click()' in source
    assert source.count("toggle.click()") == 2
