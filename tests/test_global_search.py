from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.services.security_master import SecurityMasterService


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


def _create_user(client: TestClient, name: str) -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _seed_universe(app) -> None:
    run = app.state.database.start_tushare_sync_run(
        job_scope="universe:a_share",
        as_of_date="2026-07-22",
        datasets=["stock_basic", "daily_basic"],
    )
    app.state.database.save_tushare_dataset_snapshot(
        dataset="a_share_universe",
        scope_key="all",
        as_of_date="2026-07-22",
        report_period=None,
        source_updated_at="2026-07-22T15:00:00+08:00",
        sync_run_id=run["id"],
        data_version="search-universe-v1",
        data_status="stable",
        payload={
            "as_of_date": "2026-07-22",
            "items": [
                {
                    "symbol": "000063.SZ",
                    "ts_code": "000063.SZ",
                    "name": "中兴通讯",
                    "industry": "通信设备",
                    "market": "主板",
                    "exchange": "SZSE",
                },
                {
                    "symbol": "300308.SZ",
                    "ts_code": "300308.SZ",
                    "name": "中际旭创",
                    "industry": "通信设备",
                    "market": "创业板",
                    "exchange": "SZSE",
                },
                {
                    "symbol": "600519.SS",
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "industry": "白酒",
                    "market": "主板",
                    "exchange": "SSE",
                },
            ],
        },
    )


def _group(payload: dict, key: str) -> list[dict]:
    return next(
        (group["items"] for group in payload["groups"] if group["key"] == key),
        [],
    )


def test_security_master_prefers_local_a_share_chinese_name(app) -> None:
    _seed_universe(app)
    resolver = SecurityMasterService(app.state.database)

    assert resolver.display_name(
        "000063.SZ", "ZTE Corporation"
    ) == "中兴通讯"

    public = app.state.research_reports.public_report(
        {
            "id": "report-english-name",
            "symbol": "000063.SZ",
            "name": "ZTE Corporation",
            "title": "ZTE Corporation研究快照",
            "summary": "继续研究 ZTE Corporation。",
            "body": "ZTE Corporation 的证据仍需核验。",
            "status": "preview",
            "generated_at": "2026-07-22T15:00:00+08:00",
            "market_timestamp": "2026-07-22T15:00:00+08:00",
            "evidence": {"display_name": "ZTE Corporation"},
            "fingerprint": "english-name",
            "run_id": None,
        }
    )
    assert public["name"] == "中兴通讯"
    assert public["title"] == "中兴通讯研究快照"
    assert "ZTE Corporation" not in str(public)


def test_global_search_finds_market_and_private_research_assets(app) -> None:
    _seed_universe(app)
    owner = TestClient(app)
    _create_user(owner, "Search Owner")
    watchlist = owner.post(
        "/me/watchlist",
        json={
            "symbol": "000063",
            "name": "中兴通讯",
            "market": "A股",
            "thesis": "持续核验通信设备订单与现金流",
        },
    )
    assert watchlist.status_code == 200
    conversation = owner.post(
        "/me/conversations", json={"title": "中兴通讯下跌原因研究"}
    )
    assert conversation.status_code == 201

    stock_search = owner.get("/v1/search", params={"q": "中兴"})
    assert stock_search.status_code == 200
    stock_payload = stock_search.json()
    assert stock_payload["contract_version"] == "global_search_v1"
    assert _group(stock_payload, "stocks")[0]["symbol"] == "000063.SZ"
    assert _group(stock_payload, "workspaces")[0]["symbol"] == "000063.SZ"
    assert _group(stock_payload, "conversations")[0]["id"] == conversation.json()["id"]

    industry_search = owner.get("/v1/search", params={"q": "通信设备"})
    assert industry_search.status_code == 200
    industry = _group(industry_search.json(), "industries")[0]
    assert industry["title"] == "通信设备"
    assert "2 只股票" in industry["subtitle"]
    assert "question" not in industry
    assert industry["industry"] == "通信设备"
    assert industry["url"].startswith("/research?mode=screening&industry=")


def test_global_search_keeps_conversations_user_isolated(app) -> None:
    owner = TestClient(app)
    other = TestClient(app)
    _create_user(owner, "Search Isolation Owner")
    _create_user(other, "Search Isolation Other")
    private = other.post(
        "/me/conversations", json={"title": "绝密新能源研究计划"}
    )
    assert private.status_code == 201

    owner_payload = owner.get("/v1/search", params={"q": "绝密新能源"}).json()
    other_payload = other.get("/v1/search", params={"q": "绝密新能源"}).json()

    assert _group(owner_payload, "conversations") == []
    assert _group(other_payload, "conversations")[0]["id"] == private.json()["id"]


def test_human_routes_and_frontend_state_contract_are_refreshable(client) -> None:
    for path in (
        "/today",
        "/search?q=通信设备",
        "/watchlist",
        "/stocks/000063.SZ?tab=ai",
        "/research/new",
        "/reviews?tab=trades",
        "/account",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "清数智算" in response.text

    page = frontend_source()
    for fragment in (
        'api(`/v1/search?q=${encodeURIComponent(query)}&limit=8`)',
        "function readWorkspaceRoute()",
        "function syncWorkspaceUrl(mode = \"push\")",
        'window.addEventListener("popstate"',
        'state.stockSpaceTab || "overview"',
        'state.selectedTradeReviewId && state.reviewTab === "trades"',
        'activateStockSpaceTab(initialRoute.stockTab || "overview", {historyMode: "none"})',
        'id="globalSearchResults"',
        'async function openGlobalSearchPage(query, options = {})',
        'function openAiFromSearch(query = state.searchQuery)',
        'if (item.type === "industry")',
        'else if (event.currentTarget.value.trim()) void openGlobalSearchPage',
    ):
        assert fragment in page
    assert 'const item = {type: "ai"' not in page
