from pathlib import Path


DEMO_HTML = Path(__file__).parents[1] / "app" / "static" / "demo.html"
FRONTEND_ASSETS = (
    "demo.css",
    "qs-format.js",
    "qs-screening.js",
    "demo.js",
    "qs-agent-entry.js",
    "qs-workspace.js",
    "qs-reader.js",
    "qs-agent-ui.js",
    "qs-knowledge.js",
    "qs-home.js",
    "qs-watchlist.js",
    "qs-market.js",
    "qs-stock-core.js",
    "qs-stock-workflow.js",
    "qs-stock-space.js",
    "qs-deep-stock.js",
    "qs-review.js",
    "qs-chat-runtime.js",
    "demo-boot.js",
)


def frontend_source() -> str:
    static = DEMO_HTML.parent
    return "\n".join(
        [DEMO_HTML.read_text(encoding="utf-8")]
        + [(static / name).read_text(encoding="utf-8") for name in FRONTEND_ASSETS]
    )


def test_demo_connects_action_plans_and_trade_reviews() -> None:
    page = frontend_source()

    for fragment in (
        "apiResult(`/v1/stocks/${encoded}/page?range=1y`)",
        "const actionPlansPayload = workspace?.action_plans || null;",
        "api(`/v1/stocks/${encodeURIComponent(symbol)}/action-plans`",
        "api(`/v1/action-plans/${encodeURIComponent(plan.id)}`",
        "api(`/v1/action-plans/${encodeURIComponent(plan.id)}/transition`",
        "const tradeReviewsPayload = workspace?.trade_reviews || null;",
        "api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/generate-draft`",
        "function appendAIWritebackCandidate(host, candidate, options = {})",
        'candidate.candidate_type === "action_plan"',
        'candidate.candidate_type === "review_draft"',
        "确认保存计划草稿",
        "确认写入可编辑草稿",
        "api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/draft`",
        "api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/confirm`",
        "api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/archive`",
        "api(`/v1/trade-reviews/${encodeURIComponent(review.id)}/followups`",
        "function appendTradeReviewFollowup(container, review, refreshCallback = null)",
        "把复盘改进变成下一步",
        "保存为观察任务",
        "形成判断草稿",
        "确认更新当前判断",
        "function renderActionPlanWorkspace(symbol, plans, positionWorkspace)",
        "function renderTradeReviewWorkspace(symbol, reviews)",
        "renderActionPlanWorkspace(symbol, plans, positionWorkspace)",
        "renderTradeReviewWorkspace(currentSymbol, reviews)",
        '["saved", "partially_executed"].includes(item.status) && String(item.id) === String(preferredPlanId)',
        '["saved", "partially_executed"].includes(item.status) && item.action_type === type.value',
        'headers: {"Idempotency-Key": actionPlanIdempotencyKey}',
        "JSON.stringify({base_version: tradeReviewVersion(review)?.version_no || 0})",
        "系统只检查用户条件，不生成建议",
        "价格结果和逻辑结果分开呈现",
        "plan_id",
        "action_type",
        "trigger_text",
        "target_position_percent",
        "base_version",
    ):
        assert fragment in page


def test_demo_keeps_structured_answer_body_hidden_until_details_is_open() -> None:
    page = frontend_source()

    assert (
        ".structured-answer:not([open]) > .structured-answer-body { display: none; }"
        in page
    )


def test_demo_uses_only_supported_plan_and_review_statuses() -> None:
    page = frontend_source()

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


def _function_section(page: str, start: str, end: str) -> str:
    start_index = page.index(start)
    return page[start_index : page.index(end, start_index)]


def test_demo_reuses_one_idempotency_key_per_created_form() -> None:
    page = frontend_source()
    cases = (
        (
            "function showPositionOpeningForm",
            "function showPositionOperationForm",
            'const openingIdempotencyKey = positionIdempotencyKey("opening");',
            'headers: {"Idempotency-Key": openingIdempotencyKey}',
        ),
        (
            "function showPositionOperationForm",
            "function showPositionAdjustmentForm",
            'const operationIdempotencyKey = positionIdempotencyKey("operation");',
            'headers: {"Idempotency-Key": operationIdempotencyKey}',
        ),
        (
            "function showPositionAdjustmentForm",
            "function showPositionRevisionForm",
            'const adjustmentIdempotencyKey = positionIdempotencyKey("adjustment");',
            'headers: {"Idempotency-Key": adjustmentIdempotencyKey}',
        ),
        (
            "function showPositionRevisionForm",
            "function renderPositionWorkspace",
            'const revisionIdempotencyKey = positionIdempotencyKey("revision");',
            'headers: {"Idempotency-Key": revisionIdempotencyKey}',
        ),
        (
            "function showActionPlanForm",
            "async function transitionActionPlan",
            'const actionPlanIdempotencyKey = plan ? null : positionIdempotencyKey("action-plan");',
            'headers: {"Idempotency-Key": actionPlanIdempotencyKey}',
        ),
    )

    for start, end, declaration, header in cases:
        section = _function_section(page, start, end)
        assert section.count(declaration) == 1
        assert section.count(header) == 1
        assert section.index(declaration) < section.index(
            'form.addEventListener("submit"'
        )
        assert section.index('form.addEventListener("submit"') < section.index(header)


def test_demo_uses_local_date_for_opening_position() -> None:
    page = frontend_source()
    section = _function_section(
        page, "function showPositionOpeningForm", "function showPositionOperationForm"
    )

    assert "function localDateValue(date = new Date())" in page
    assert "asOf.value = localDateValue();" in section
    assert "asOf.value = new Date().toISOString().slice(0, 10)" not in section


def test_demo_agent_task_entry_requests_live_verification_and_draft_only() -> None:
    page = frontend_source()
    section = _function_section(
        page, "function renderStockSpaceTasks", "function renderStockSpaceHistory"
    )

    for fragment in (
        "请立即核验",
        "当前可用的实时数据、资料库和证据链",
        "反方证据、数据时间和失效条件",
        "生成观察任务草稿供我确认",
        "正式任务必须等我点击确认后才写入",
        "continueDeepStockConversation(agentTaskPrompt)",
        "确认前不会创建个人任务。",
    ):
        assert fragment in page
    assert 'ask.addEventListener("click", () => { void api(' not in section


def test_demo_offers_direct_resume_of_latest_saved_research() -> None:
    page = frontend_source()

    for fragment in (
        'id="agentResumeResearch"',
        'id="agentResumeOpen"',
        "继续上次研究",
        "function latestConversationItem()",
        "function syncAgentResumeResearch()",
        'button.dataset.conversationId = item?.id || "";',
        'await openConversation(conversationId, true, "push");',
    ):
        assert fragment in page

    resume_section = _function_section(
        page, "function syncAgentResumeResearch", "function normalizedStockLookup"
    )
    assert "sendChat(" not in resume_section
    assert "startNewConversation(" not in resume_section


def test_demo_restores_agent_route_before_loading_unrelated_dashboards() -> None:
    page = frontend_source()
    boot_section = page[page.index("state.workspaceBootPromise =") :]

    for fragment in (
        'if (initialRoute.page === "agent")',
        "await Promise.all([loadConversations(false, false), loadDeepStock()]);",
        'await restoreWorkspaceRoute(initialRoute, "replace");',
        "void Promise.allSettled([",
        "loadTodayOverview(),",
        "loadKnowledge()",
    ):
        assert fragment in boot_section

    agent_branch = boot_section[
        boot_section.index('if (initialRoute.page === "agent")') :
        boot_section.index("await loadWatchlist();")
    ]
    assert agent_branch.index("await restoreWorkspaceRoute") < agent_branch.index(
        "void Promise.allSettled"
    )


def test_demo_loads_li_zong_route_before_unrelated_dashboards() -> None:
    page = frontend_source()
    boot_section = page[page.index("state.workspaceBootPromise =") :]

    first_screening_branch = boot_section.index(
        'if (initialRoute.page === "screening")'
    )
    route_screening_branch = boot_section.index(
        'if (initialRoute.page === "screening")', first_screening_branch + 1
    )
    screening_branch = boot_section[
        route_screening_branch : boot_section.index(
            'if (initialRoute.page === "review")', route_screening_branch
        )
    ]
    assert 'initialRoute.screeningSection === "li_zong"' in screening_branch
    assert "await loadLiZongStrategy();" in screening_branch
    assert 'await restoreWorkspaceRoute(initialRoute, "replace");' in screening_branch
    assert "void Promise.allSettled([" in screening_branch
    assert screening_branch.index("await loadLiZongStrategy") < screening_branch.index(
        "loadWatchlist(),"
    )
    assert screening_branch.index("await restoreWorkspaceRoute") < screening_branch.index(
        "void Promise.allSettled"
    )


def test_demo_filters_saved_conversations_by_explicit_stock_target() -> None:
    page = frontend_source()

    for fragment in (
        "function conversationResearchTargets(item)",
        "function conversationStockFilterOptions(items = [])",
        "function syncConversationScopeOptions()",
        'group.label = "具体股票";',
        'option.value = `stock:${item.symbol}`;',
        'state.conversationScope.startsWith("stock:")',
        'conversationScopeKey(item) === "stock"',
        "conversationResearchTargets(item).some(target => target.symbol === stockSymbol)",
    ):
        assert fragment in page

    filter_section = _function_section(
        page, "function filteredConversationItems", "function syncConversationFilterControls"
    )
    assert "conversationTopicKey" not in filter_section


def test_demo_exposes_stock_workspace_load_failure_and_retry() -> None:
    page = frontend_source()
    section = _function_section(
        page,
        "async function loadDeepStockOverview",
        "async function openDeepStockSymbol",
    )

    for fragment in (
        "apiResult(`/v1/stocks/${encoded}/page?range=1y`)",
        'const moduleData = name => pageModules[name]?.status === "available" ? pageModules[name].data : null;',
        "const workspaceLoadError = workspace ? null : (",
        "股票研究空间未完整加载",
        "不会把缺失内容显示成“没有数据”",
        "重新加载不会清空已保存的判断、任务、持仓或历史对话",
        "重新加载股票空间",
        "await loadDeepStockOverview(symbol);",
    ):
        assert fragment in section
    assert "optionalApi(`/v1/stocks/${encoded}/workspace`)" not in section
    assert "optionalApi(`/stocks/${encoded}/history?range=1y`)" not in section


def test_demo_displays_stock_screen_data_contract_and_missing_reasons() -> None:
    page = frontend_source()
    section = _function_section(
        page, "function renderStockScreener", "async function loadStockScreener"
    )

    for fragment in (
        "const contract = payload?.data_contract || {};",
        "股票池 ${Number(snapshotCoverage.available || 0)",
        'coverageLabel("估值", coverage.valuation)',
        'coverageLabel("20日收益", coverage.return_20d)',
        "数据覆盖 ${coverageSummary}",
        "数据版本 ${dataVersion.slice(-8)}",
        "item.missing_reasons || []",
        "数据缺口：",
    ):
        assert fragment in section


def test_demo_explains_trade_review_trigger_and_horizon() -> None:
    page = frontend_source()
    section = _function_section(
        page,
        "function showPositionOperationForm",
        "function showPositionAdjustmentForm",
    )

    assert "只有减仓或卖出会创建交易复盘" in section
    assert "需等待 3 个后续交易日数据" in section
    assert "买入和加仓不会创建复盘" in section


def test_demo_restores_pending_review_drafts_before_offering_generation() -> None:
    page = frontend_source()

    for fragment in (
        "pendingReviewDrafts: {}",
        "pendingReviewDraftsLoaded: false",
        'api("/v1/ai-writebacks?status=pending_confirmation&limit=300")',
        'candidate.candidate_type === "review_draft"',
        "candidate?.payload?.review_id",
        "function appendPendingReviewDraftCandidate(host, review, refreshCallback)",
        "appendAIWritebackCandidate(host, candidate, {",
        "loadPendingReviewDrafts()",
        'review.status === "ready" && !pendingCandidate && state.pendingReviewDraftsLoaded',
        'reviewStatus === "ready" && !pendingCandidate && state.pendingReviewDraftsLoaded',
        "appendPendingReviewDraftCandidate(container, review",
        "appendPendingReviewDraftCandidate(card, review",
        "正在核对已有草稿…",
    ):
        assert fragment in page


def test_demo_deduplicates_stock_page_and_pending_draft_requests() -> None:
    page = frontend_source()

    for fragment in (
        "pendingReviewDraftsPromise: null",
        "deepStockOverviewPromises: {}",
        "if (state.pendingReviewDraftsPromise) return state.pendingReviewDraftsPromise;",
        "if (state.deepStockOverviewPromises[canonical])",
        "return state.deepStockOverviewPromises[canonical];",
        "const request = loadDeepStockOverviewOnce(canonical);",
        'activateWorkspace("deep_stock", {historyMode: "none", loadStockOverview: false});',
    ):
        assert fragment in page

    load_sessions = _function_section(
        page,
        "async function loadDeepStock({force = false} = {})",
        "async function startDeepStockSession",
    )
    assert "loadDeepStockOverview(selected)" not in load_sessions
