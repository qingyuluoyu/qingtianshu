from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _stage(payload: dict, key: str) -> dict:
    return next(item for item in payload["stages"] if item["key"] == key)


def _completed_run() -> dict:
    return {
        "id": None,
        "status": "completed",
        "usage": {"output_guard": {"passed": True}},
    }


def test_deep_stock_api_binds_existing_conversation_and_is_user_isolated(app):
    client = TestClient(app)
    user = _create_user(client, "Deep Stock User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "关注算力业务、利润质量和现金流能否同步改善",
    )
    conversation = client.post(
        "/me/conversations", json={"title": "中兴通讯原有研究"}
    ).json()

    created = client.post(
        "/me/deep-stock",
        json={
            "symbol": "000063",
            "conversation_id": conversation["id"],
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["symbol"] == "000063.SZ"
    assert payload["name"] == "中兴通讯"
    assert payload["conversation"]["title"] == "个股研究｜中兴通讯"
    assert payload["conversation_id"] == conversation["id"]
    assert payload["workflow_version"] == "guided_deep_stock_v1"
    assert payload["progress"] == {"completed": 1, "total": 7, "percent": 14}
    assert _stage(payload, "original_thesis")["status"] == "completed"
    assert _stage(payload, "company_industry")["status"] == "in_progress"
    assert payload["current_stage"]["key"] == "company_industry"
    assert payload["evidence_coverage"]["summary"] == {
        "sufficient": 0,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 6,
        "total": 6,
        "refresh_attention": 0,
    }
    assert len(payload["coverage_tasks"]) == 6

    guarded = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=conversation["id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请研究中兴通讯",
        run={"id": None, "status": "guarded"},
        evidence={},
    )
    assert guarded is not None
    assert guarded["evidence_coverage"]["summary"]["total"] == 6
    assert guarded["evidence_coverage"]["summary"]["unavailable"] == 6
    assert len(guarded["coverage_tasks"]) == 6

    listed = client.get("/me/deep-stock")
    assert listed.status_code == 200
    assert listed.json()["summary"]["active"] == 1
    assert listed.json()["items"][0]["conversation"]["message_count"] == 0
    assert client.get("/me/deep-stock/000063").status_code == 200

    other = TestClient(app)
    _create_user(other, "Deep Stock Other")
    assert other.get("/me/deep-stock/000063").status_code == 404


def test_deep_stock_rejects_silent_primary_conversation_rebinding(app):
    client = TestClient(app)
    _create_user(client, "Deep Stock Binding User")
    first = client.post("/me/conversations", json={"title": "中兴主会话"}).json()
    second = client.post("/me/conversations", json={"title": "另一条会话"}).json()

    created = client.post(
        "/me/deep-stock",
        json={"symbol": "000063", "conversation_id": first["id"]},
    )
    assert created.status_code == 201

    replaced = client.post(
        "/me/deep-stock",
        json={"symbol": "000063", "conversation_id": second["id"]},
    )
    assert replaced.status_code == 409
    assert "不能静默替换" in replaced.json()["detail"]
    assert client.get("/me/deep-stock/000063").json()["conversation_id"] == first["id"]


def test_deep_stock_rejects_one_conversation_bound_to_two_stocks(app):
    client = TestClient(app)
    _create_user(client, "Deep Stock Shared Conversation User")
    conversation = client.post(
        "/me/conversations", json={"title": "单股主会话"}
    ).json()

    assert client.post(
        "/me/deep-stock",
        json={"symbol": "000063", "conversation_id": conversation["id"]},
    ).status_code == 201
    shared = client.post(
        "/me/deep-stock",
        json={"symbol": "300308", "conversation_id": conversation["id"]},
    )

    assert shared.status_code == 409
    assert "另一只股票" in shared.json()["detail"]


def test_market_diagnosis_does_not_mutate_bound_stock_research_state(app):
    client = TestClient(app)
    user = _create_user(client, "Deep Stock Market Boundary User")
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    before = client.get("/me/deep-stock/000063").json()

    observed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol=None,
        intent="market_brief",
        message="请诊断当前A股大盘",
        run={
            "id": "market-run-must-not-bind",
            "status": "completed",
            "usage": {"output_guard": {"passed": True}},
        },
        evidence={
            "market_drivers": {"status": "available"},
            "market_breadth": {"status": "available"},
        },
    )

    assert observed is not None
    after = client.get("/me/deep-stock/000063").json()
    assert after["progress"] == before["progress"]
    assert after["stages"] == before["stages"]
    assert after["evidence_coverage"] == before["evidence_coverage"]
    assert after["coverage_history"] == before["coverage_history"]
    assert after["latest_run_id"] == before["latest_run_id"]


def test_screening_candidate_entry_is_saved_without_completing_research_stage(app):
    client = TestClient(app)
    _create_user(client, "Screening Entry User")

    created = client.post(
        "/me/deep-stock",
        json={
            "symbol": "000063",
            "entry_context": {
                "source_kind": "stock_screen",
                "source_label": "经营改善候选",
                "display_name": "中兴通讯",
                "profile_key": "quality",
                "as_of_date": "2026-07-22",
                "candidate_status": "ready",
                "matched_reasons": [
                    "营收同比保持增长",
                    "毛利率高于模板下限",
                ],
                "research_focus": "先核验改善是否来自主营并转化为现金流。",
                "attention_flags": ["净利润同比下降，需要先排除低质量增长。"],
                "missing_fields": ["最新公告原文", "现金流变化原因"],
            },
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["symbol"] == "000063.SZ"
    assert payload["progress"]["completed"] == 0
    assert payload["current_stage"]["key"] == "original_thesis"
    assert payload["research_entry"] == {
        "source_kind": "stock_screen",
        "source_label": "经营改善候选",
        "display_name": "中兴通讯",
        "profile_key": "quality",
        "as_of_date": "2026-07-22",
        "candidate_status": "ready",
        "matched_reasons": ["营收同比保持增长", "毛利率高于模板下限"],
        "research_focus": "先核验改善是否来自主营并转化为现金流。",
        "attention_flags": ["净利润同比下降，需要先排除低质量增长。"],
        "missing_fields": ["最新公告原文", "现金流变化原因"],
        "status": "user_selected_context",
        "limitations": [
            "这是用户从筛选结果进入研究空间时保存的研究线索，"
            "不会直接完成研究阶段，仍需用正式行情、财务和公告证据核验。"
        ],
        "updated_at": payload["research_entry"]["updated_at"],
    }
    assert "经营改善候选" in payload["next_question"]
    assert "筛选入口待核验：最新公告原文" in payload["unresolved_items"]

    workspace = client.get("/v1/stocks/000063/workspace")
    assert workspace.status_code == 200
    workspace_payload = workspace.json()
    assert workspace_payload["name"] == "中兴通讯"
    assert workspace_payload["research_entry"]["profile_key"] == "quality"
    assert workspace_payload["research_entry"]["research_focus"] == (
        "先核验改善是否来自主营并转化为现金流。"
    )
    assert workspace_payload["pending_actions"][0]["next_step"] == (
        "先核验改善是否来自主营并转化为现金流。"
    )
    assert workspace_payload["pending_actions"][0]["source"] == "screening_entry"
    assert "经营改善候选" in workspace_payload["pending_actions"][0]["title"]

    repeated = client.post(
        "/me/deep-stock",
        json={
            "symbol": "000063.SZ",
            "entry_context": {
                "source_kind": "li_zong_strategy",
                "source_label": "李总策略",
                "display_name": "中兴通讯",
                "candidate_status": "qualified",
                "matched_reasons": ["总市值严格大于150亿元"],
            },
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["conversation_id"] == payload["conversation_id"]
    assert repeated.json()["research_entry"]["source_kind"] == "li_zong_strategy"

    other = TestClient(app)
    _create_user(other, "Screening Entry Other User")
    assert other.get("/me/deep-stock/000063").status_code == 404


def test_li_zong_history_entry_preserves_all_nine_candidate_rule_reasons(app):
    client = TestClient(app)
    _create_user(client, "Li Zong History Entry User")
    reasons = [f"候选规则 {index}" for index in range(1, 10)]

    response = client.post(
        "/me/deep-stock",
        json={
            "symbol": "600961.SS",
            "entry_context": {
                "source_kind": "li_zong_strategy",
                "source_label": "李总策略历史回放",
                "display_name": "株冶集团",
                "profile_key": "li_zong_history_v2",
                "as_of_date": "2026-07-01",
                "candidate_status": "historical_triggered",
                "matched_reasons": reasons,
                "missing_fields": [],
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["research_entry"]["matched_reasons"] == reasons


def test_guarded_runs_do_not_complete_stages_but_valid_evidence_does(app):
    client = TestClient(app)
    user = _create_user(client, "Deep Workflow User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证利润、现金流和业务结构",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    evidence = {
        "metrics": {
            "latest_close": 40.0,
            "return_20d_pct": 8.0,
            "ma20": 38.0,
            "rsi_14": 55.0,
        },
        "research_frame": {"missing_information": []},
        "business_structure": {
            "status": "available",
            "anchor_report_date": "2025-12-31",
            "dimensions": [{"classification": "product"}],
            "sources": [
                {
                    "name": "测试主营结构源",
                    "url": "https://example.invalid/business",
                }
            ],
        },
        "fundamentals": {
            "status": "available",
            "source": "测试结构化财务源",
            "financial_periods": [{"report_period": "2026-03-31"}],
            "valuation": {"price": 40.0, "pe_ttm": 20.0},
        },
        "earnings_quality": {
            "status": "available",
            "report_period": "2026-03-31",
            "factors": [{"label": "利润质量"}],
            "filing_evidence": {
                "document": {"source": "测试财报原文源"}
            },
        },
        "financial_drivers": {
            "status": "available",
            "source": "测试三表计算源",
            "report_period": "2026-03-31",
            "confirmed_mechanical_drivers": [{"label": "毛利变化"}],
        },
        "peer_comparison": {
            "status": "available",
            "sources": [{"name": "测试固定同行源"}],
            "metrics": [{"key": "pe_ttm"}],
            "peers": [{"symbol": "600498.SS"}],
        },
        "analyst_expectations": {
            "status": "available",
            "sources": [{"name": "测试分析师预期源"}],
            "industry": "通信设备",
            "forecast_eps": [{"year": 2026, "value": 1.4}],
        },
        "event_timeline": {
            "status": "available",
            "events": [{"title": "季度报告", "source": "测试公告源"}],
        },
        "a_share_information": {
            "status": "available",
            "announcements": [
                {"title": "季度报告", "source": "测试公告聚合源"}
            ],
        },
        "evidence_debate": {
            "status": "available",
            "bear_case": [
                {
                    "claim": "利润承压",
                    "evidence": "净利润同比下降",
                    "source": "structured_fundamentals",
                }
            ],
            "risk_committee": [
                {
                    "risk": "现金流背离",
                    "evidence": "经营现金流弱于利润",
                    "source": "deterministic_financial_driver",
                }
            ],
        },
        "analysis_board": {
            "modules": [
                {"key": "fundamental", "label": "基本面", "status": "ready"}
            ]
        },
        "conditional_outlook": {
            "status": "available",
            "label": "条件观察",
            "scenarios": [{"label": "区间"}],
        },
    }

    guarded = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析中兴通讯",
        run={"id": None, "status": "guarded"},
        evidence=evidence,
    )
    assert guarded is not None
    assert guarded["progress"]["completed"] == 1
    assert "研究进度保持不变" in guarded["unresolved_items"][-1]
    assert "输出校验" not in " ".join(guarded["unresolved_items"])

    specialized = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="中兴通讯靠什么赚钱，主营结构如何？",
        run={"id": None, "status": "preview"},
        evidence={"status": "available", "rows": [{"item_name": "运营商网络"}]},
    )
    assert specialized is not None
    assert specialized["progress"]["completed"] == 1
    assert _stage(specialized, "company_industry")["status"] == "in_progress"
    specialized_coverage = {
        item["key"]: item
        for item in specialized["evidence_coverage"]["dimensions"]
    }
    assert specialized_coverage["company_operating"]["coverage_status"] == "sufficient"
    assert len(specialized["coverage_history"]) == 1

    researched = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析并主动检查反方证据",
        run=_completed_run(),
        evidence=evidence,
    )
    assert researched is not None
    assert researched["progress"]["completed"] == 6
    assert _stage(researched, "counterevidence")["status"] == "completed"
    assert _stage(researched, "invalidation_next")["status"] == "in_progress"

    completed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请总结失效条件、下一步需要核验的证据和观察条件",
        run=_completed_run(),
        evidence=evidence,
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["progress"]["completed"] == 7
    assert completed["current_stage"] is None
    coverage = completed["evidence_coverage"]
    assert coverage["summary"] == {
        "sufficient": 6,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 0,
        "total": 6,
        "refresh_attention": 0,
    }
    assert {item["key"] for item in coverage["dimensions"]} == {
        "company_operating",
        "financial_quality",
        "industry_relative",
        "valuation",
        "technical_state",
        "risk_events",
    }

    stored_user = app.state.database.get_user(user["id"])
    snapshot = (
        Path(stored_user["workspace_path"])
        / "deep-stock"
        / "000063_SZ.json"
    )
    assert snapshot.is_file()
    assert '"guided_deep_stock_v1"' in snapshot.read_text(encoding="utf-8")

    restored = client.get("/me/deep-stock/000063").json()
    assert restored["evidence_coverage"]["summary"]["sufficient"] == 6
    assert restored["coverage_tasks"] == []
    assert len(restored["coverage_history"]) == 3

    thinned = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="只刷新一个很薄的专项数据包",
        run=_completed_run(),
        evidence={
            "business_structure": {"status": "available"},
            "analysis_board": {"modules": []},
        },
    )
    assert thinned is not None
    assert thinned["evidence_coverage"]["summary"] == {
        "sufficient": 6,
        "partial": 0,
        "insufficient": 0,
        "unavailable": 0,
        "total": 6,
        "refresh_attention": 6,
    }
    assert len(thinned["coverage_tasks"]) == 6
    assert all(
        task["coverage_status"] == "sufficient"
        and task["last_observed_status"] != "sufficient"
        for task in thinned["coverage_tasks"]
    )
    history_before_failure = list(thinned["coverage_history"])

    failed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="本轮模型输出未通过校验",
        run={"id": None, "status": "guarded"},
        evidence={},
    )
    assert failed is not None
    assert failed["evidence_coverage"]["summary"]["sufficient"] == 6
    assert failed["coverage_history"] == history_before_failure
    assert "研究进度保持不变" in failed["unresolved_items"][-1]

    restored_after_failure = client.get("/me/deep-stock/000063").json()
    assert restored_after_failure["evidence_coverage"] == failed["evidence_coverage"]
    assert restored_after_failure["coverage_tasks"] == failed["coverage_tasks"]
    assert restored_after_failure["coverage_history"] == history_before_failure


def test_thin_packets_do_not_advance_research_stages(app):
    client = TestClient(app)
    user = _create_user(client, "Coverage Gate User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证业务结构和利润质量",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()

    observed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="stock_research",
        message="请完整分析中兴通讯",
        run=_completed_run(),
        evidence={
            "business_structure": {"status": "available"},
            "fundamentals": {"status": "available"},
            "peer_comparison": {"status": "available"},
            "event_timeline": {"status": "available"},
            "analysis_board": {"modules": []},
        },
    )

    assert observed is not None
    assert observed["progress"]["completed"] == 1
    company_stage = _stage(observed, "company_industry")
    assert company_stage["status"] == "needs_review"
    assert "核心证据包" not in " ".join(company_stage["review_reasons"])
    assert "证据覆盖尚未达到完成门槛" in " ".join(
        company_stage["review_reasons"]
    )
    coverage = {
        item["key"]: item for item in observed["evidence_coverage"]["dimensions"]
    }
    assert coverage["company_operating"]["coverage_status"] == "insufficient"
    assert coverage["financial_quality"]["coverage_status"] == "insufficient"


def test_completed_run_requires_guard_pass_and_available_evidence(app):
    client = TestClient(app)
    user = _create_user(client, "Strict Stage Gate User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证主营结构证据",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    evidence = {
        "status": "available",
        "rows": [{"item_name": "运营商网络"}],
        "sources": [{"name": "测试主营结构源"}],
    }

    missing_guard = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="中兴通讯靠什么赚钱？",
        run={"id": None, "status": "completed"},
        evidence=evidence,
    )
    assert missing_guard is not None
    assert missing_guard["progress"]["completed"] == 1
    assert _stage(missing_guard, "company_industry")["status"] == "in_progress"
    assert any(
        "研究进度保持不变" in item
        for item in missing_guard["unresolved_items"]
    )
    assert "输出守卫" not in " ".join(missing_guard["unresolved_items"])

    failed_evidence = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="继续核验主营结构。",
        run=_completed_run(),
        evidence={**evidence, "status": "failed"},
    )
    assert failed_evidence is not None
    assert failed_evidence["progress"]["completed"] == 1
    assert any(
        "核心证据尚不完整" in item
        for item in failed_evidence["unresolved_items"]
    )


def test_sufficient_coverage_without_source_is_needs_review_and_restores(app):
    client = TestClient(app)
    user = _create_user(client, "Stage Source Gate User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证主营结构证据来源",
    )
    session = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    evidence = {
        "status": "available",
        "rows": [{"item_name": "运营商网络"}],
    }

    needs_review = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="中兴通讯靠什么赚钱？",
        run=_completed_run(),
        evidence=evidence,
    )
    assert needs_review is not None
    stage = _stage(needs_review, "company_industry")
    assert stage["status"] == "needs_review"
    assert stage["coverage_gate"] == {"company_operating": "sufficient"}
    assert stage["source_refs"] == []
    assert "可追溯来源" in " ".join(stage["review_reasons"])

    restored = client.get("/me/deep-stock/000063").json()
    restored_stage = _stage(restored, "company_industry")
    assert restored_stage["status"] == "needs_review"
    assert restored_stage["review_reasons"] == stage["review_reasons"]

    completed = app.state.deep_stock.observe_chat(
        user_id=user["id"],
        conversation_id=session["conversation_id"],
        symbol="000063.SZ",
        intent="business_structure",
        message="继续核验主营结构。",
        run=_completed_run(),
        evidence={
            **evidence,
            "sources": [
                {
                    "name": "测试主营结构源",
                    "url": "https://example.invalid/business",
                }
            ],
        },
    )
    assert completed is not None
    completed_stage = _stage(completed, "company_industry")
    assert completed_stage["status"] == "completed"
    assert completed_stage["source_refs"] == [
        "测试主营结构源",
        "https://example.invalid/business",
    ]


def test_legacy_completed_stages_are_reconciled_from_their_original_run(app):
    client = TestClient(app)
    user = _create_user(client, "Legacy Stage Reconcile User")
    app.state.database.upsert_watchlist(
        user["id"],
        "000063.SZ",
        "中兴通讯",
        "A股",
        "验证历史阶段是否有真实完成证据",
    )
    created = client.post("/me/deep-stock", json={"symbol": "000063"}).json()
    database = app.state.database
    run = database.create_run(
        user["id"],
        "business_structure",
        "economy",
        {"message": "中兴通讯靠什么赚钱，主营结构如何？"},
        app.state.settings.workspace_root,
    )
    evidence = {
        "status": "available",
        "rows": [{"item_name": "运营商网络"}],
        "sources": [
            {
                "name": "测试主营结构源",
                "url": "https://example.invalid/business",
            }
        ],
    }
    database.finish_run(
        run["id"],
        user["id"],
        "completed",
        evidence,
        "主营结构研究已完成。",
        {"output_guard": {"passed": True}},
    )

    raw = database.get_deep_stock_session(user["id"], "000063.SZ")
    stages = list(raw["stages"])
    company = next(item for item in stages if item["key"] == "company_industry")
    company.update(
        {
            "status": "completed",
            "completed_at": "2026-07-22T10:00:00+00:00",
            "run_id": run["id"],
            "evidence_modules": ["business_structure"],
        }
    )
    financial = next(
        item for item in stages if item["key"] == "financial_cashflow"
    )
    financial.update(
        {
            "status": "completed",
            "completed_at": "2026-07-22T10:05:00+00:00",
            "run_id": None,
            "evidence_modules": ["fundamentals"],
        }
    )
    database.save_deep_stock_session(
        user_id=user["id"],
        symbol="000063.SZ",
        name="中兴通讯",
        conversation_id=created["conversation_id"],
        workflow_version=raw["workflow_version"],
        status="active",
        stages=stages,
        evidence_modules=raw["evidence_modules"],
        unresolved_items=raw["unresolved_items"],
        next_question=raw["next_question"],
        latest_run_id=run["id"],
        latest_report_id=raw["latest_report_id"],
        completed_at=None,
    )

    reconciled = client.get("/me/deep-stock/000063").json()
    company = _stage(reconciled, "company_industry")
    financial = _stage(reconciled, "financial_cashflow")
    assert company["status"] == "completed"
    assert company["completion_gate_version"] == "stage_completion_gate_v2"
    assert company["source_refs"] == [
        "测试主营结构源",
        "https://example.invalid/business",
    ]
    assert financial["status"] == "needs_review"
    assert "部分历史研究阶段需要用当前证据重新核验" in " ".join(
        financial["review_reasons"]
    )
    assert "Run" not in " ".join(financial["review_reasons"])
    assert reconciled["progress"]["completed"] == 2
    assert reconciled["current_stage"]["key"] == "financial_cashflow"
    assert reconciled["current_stage"]["status"] == "needs_review"
    assert any(
        "部分历史研究阶段需要用当前证据重新核验" in item
        for item in reconciled["unresolved_items"]
    )

    repeated = client.get("/me/deep-stock/000063").json()
    assert repeated["stages"] == reconciled["stages"]
    assert repeated["unresolved_items"] == reconciled["unresolved_items"]
    assert repeated["progress"] == reconciled["progress"]
