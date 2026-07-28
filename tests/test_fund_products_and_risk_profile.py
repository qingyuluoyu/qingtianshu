from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.providers.funds import EastmoneyFundProvider


def _create_user(client: TestClient, name: str = "基金研究用户") -> dict:
    response = client.post("/users", json={"name": name})
    assert response.status_code == 201
    return response.json()


class _FakeFundProvider:
    def search(self, query: str, *, limit: int = 8) -> dict:
        return {
            "query": query,
            "items": [
                {
                    "code": "510300",
                    "name": "沪深300ETF测试",
                    "fund_type": "指数型-股票",
                    "asset_class": "equity_index",
                    "product_kind": "etf",
                    "nav": 4.75,
                    "nav_date": "2026-07-27",
                }
            ][:limit],
            "source": "Fake fund search",
            "source_url": "https://example.invalid/funds",
            "fetched_at": "2026-07-28T00:00:00+00:00",
            "warnings": [],
        }

    def fetch_product(self, code: str) -> dict:
        is_etf = code in {"510300", "159915"}
        return {
            "code": code,
            "name": {
                "510300": "沪深300ETF测试",
                "159915": "创业板ETF测试",
                "110022": "主动股票基金测试",
            }.get(code, f"基金{code}"),
            "product_kind": "etf" if is_etf else "fund",
            "asset_class": "equity_index" if is_etf else "equity",
            "fund_type": "指数型-股票" if is_etf else "股票型",
            "nav": 4.75 if code == "510300" else 2.31,
            "accumulated_nav": 4.75 if code == "510300" else 2.31,
            "nav_date": "2026-07-27",
            "daily_return_pct": 1.1 if code == "510300" else 0.6,
            "returns": {
                "one_month_pct": 2.0 if code == "510300" else 3.0,
                "three_month_pct": 4.0 if code == "510300" else 5.0,
                "six_month_pct": 6.0 if code == "510300" else 7.0,
                "one_year_pct": 8.0 if code == "510300" else 9.0,
            },
            "return_ranks": {},
            "purchase_status": "场内交易" if is_etf else "开放申购",
            "redemption_status": "场内交易" if is_etf else "开放赎回",
            "fees": {
                "listed_purchase_fee_pct": None if is_etf else 1.5,
                "current_channel_purchase_fee_pct": None if is_etf else 0.15,
                "scope": "申购页面展示费率",
            },
            "minimum_purchase_cny": None if is_etf else 10.0,
            "minimum_recurring_purchase_cny": None if is_etf else 10.0,
            "risk_level_upstream": "5" if is_etf else "4",
            "net_assets_cny": 100_000_000_000.0
            if code == "510300"
            else 5_000_000_000.0,
            "fund_shares": 20_000_000_000.0,
            "fund_company": "测试基金公司",
            "fund_manager": "测试经理",
            "inception_date": "2012-01-01",
            "top_holdings_summary": ["贵州茅台", "宁德时代"],
            "live_quote": (
                {
                    "price": 4.753,
                    "previous_close": 4.701,
                    "pct_change": 1.11,
                    "market_timestamp": "2026-07-27T15:00:00+08:00",
                    "fetched_at": "2026-07-28T00:00:00+00:00",
                    "source": "Fake quote",
                }
                if is_etf
                else None
            ),
            "source": "Fake fund provider",
            "source_url": f"https://example.invalid/funds/{code}",
            "fetched_at": "2026-07-28T00:00:00+00:00",
            "field_mapping": "fake_fund_v1",
            "warnings": ["测试产品事实"],
        }


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _TextResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_eastmoney_fund_provider_keeps_nav_and_etf_quote_separate() -> None:
    def get(url, **kwargs):
        if "FundBaseTypeInformation" in url:
            return _FakeResponse(
                {
                    "ErrCode": 0,
                    "Datas": {
                        "FCODE": "510300",
                        "SHORTNAME": "沪深300ETF华泰柏瑞",
                        "FTYPE": "指数型-股票",
                        "DWJZ": "4.7583",
                        "LJJZ": "2.0915",
                        "FSRQ": "2026-07-27",
                        "RZDF": "1.14",
                        "SYL_Y": "-2.92",
                        "SYL_3Y": "-0.57",
                        "SYL_6Y": "0.95",
                        "SYL_1N": "16.12",
                        "SGZT": "场内交易",
                        "SHZT": "场内交易",
                        "RISKLEVEL": "5",
                        "ENDNAV": "94872183996.4",
                        "FEGM": "18914887690",
                        "FUNDINVEST": "中际旭创,宁德时代,贵州茅台",
                    },
                }
            )
        return _FakeResponse(
            {
                "rc": 0,
                "data": {
                    "f43": 4753,
                    "f59": 3,
                    "f60": 4701,
                    "f170": 111,
                    "f48": 4_584_814_670,
                    "f47": 9_715_927,
                    "f124": 0,
                },
            }
        )

    product = EastmoneyFundProvider(http_get=get).fetch_product("510300")

    assert product["nav"] == 4.7583
    assert product["nav_date"] == "2026-07-27"
    assert product["live_quote"]["price"] == 4.753
    assert product["live_quote"]["pct_change"] == 1.11
    assert product["product_kind"] == "etf"
    assert product["asset_class"] == "equity_index"


def test_etf_quote_falls_back_to_tencent_when_eastmoney_quote_fails() -> None:
    def get(url, **kwargs):
        if "FundBaseTypeInformation" in url:
            return _FakeResponse(
                {
                    "ErrCode": 0,
                    "Datas": {
                        "FCODE": "510300",
                        "SHORTNAME": "沪深300ETF华泰柏瑞",
                        "FTYPE": "指数型-股票",
                        "DWJZ": "4.7583",
                        "FSRQ": "2026-07-27",
                        "SGZT": "场内交易",
                        "SHZT": "场内交易",
                    },
                }
            )
        if "push2.eastmoney.com" in url:
            return _FakeResponse({"rc": 102, "data": None})
        if "qt.gtimg.cn" in url:
            fields = [""] * 36
            fields[0:7] = [
                "1",
                "沪深300ETF华泰柏瑞",
                "510300",
                "4.753",
                "4.701",
                "4.702",
                "9715927",
            ]
            fields[30] = "20260727161442"
            fields[32] = "1.11"
            fields[35] = "4.753/9715927/4584814670"
            return _TextResponse(f'v_sh510300="{"~".join(fields)}";')
        raise AssertionError(url)

    product = EastmoneyFundProvider(http_get=get).fetch_product("510300")

    assert product["live_quote"]["price"] == 4.753
    assert product["live_quote"]["pct_change"] == 1.11
    assert product["live_quote"]["turnover_cny"] == 4_584_814_670
    assert product["live_quote"]["source"] == "Tencent Realtime Quote"


def test_fund_product_api_persists_and_compares_same_windows(client, app) -> None:
    _create_user(client)
    app.state.fund_products.provider = _FakeFundProvider()

    detail = client.get("/fund-products/510300?refresh=true")
    assert detail.status_code == 200
    assert detail.json()["nav"] == 4.75
    assert detail.json()["live_quote"]["price"] == 4.753

    comparison = client.get("/fund-products?codes=510300,159915&refresh=true")
    assert comparison.status_code == 200
    payload = comparison.json()
    assert payload["contract_version"] == "fund_product_comparison_v1"
    assert payload["comparability"]["same_nav_date"] is True
    assert [item["code"] for item in payload["products"]] == [
        "510300",
        "159915",
    ]
    assert app.state.database.latest_fund_product_snapshot("510300") is not None


def test_fund_codes_route_to_product_research_not_stock_research(client, app) -> None:
    user = _create_user(client, "ETF比较用户")
    app.state.fund_products.provider = _FakeFundProvider()

    response = client.post(
        "/me/chat",
        json={
            "message": "比较510300 ETF和159915 ETF，按同一窗口说明差异。",
            "execute_agent": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "general_research"
    assert payload.get("symbol") is None
    assert payload["research_targets"] == []
    conversation = client.get(
        f"/me/conversations/{payload['conversation_id']}"
    ).json()
    assert conversation["conversation_scope"] == "funds"
    comparison = payload["evidence"]["fund_product_context"]["comparison"]
    assert len(comparison["products"]) == 2
    run = app.state.database.get_run(payload["run_id"], user["id"])
    prompt_path = (
        Path(app.state.database.get_user(user["id"])["workspace_path"])
        / "runs"
        / run["id"]
        / "prompt.md"
    )
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "基金与ETF当前产品事实要求" in prompt
    assert "场内ETF的 live_quote 是成交报价" in prompt


def _complete_answers() -> dict[str, str]:
    return {
        "fund_use_horizon": "long",
        "liquidity_need": "medium",
        "loss_tolerance": "medium",
        "emergency_reserve": "adequate",
        "debt_burden": "low",
        "investment_experience": "beginner",
        "primary_objective": "balanced",
    }


def test_risk_profile_requires_explicit_confirmation_before_agent_use(
    client, app
) -> None:
    user = _create_user(client, "适合性问卷用户")

    draft = client.put(
        "/me/risk-profile/draft",
        json={"base_version": 0, "answers": _complete_answers()},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    assert app.state.risk_profiles.confirmed_context(user["id"]) is None

    before = client.post(
        "/me/chat",
        json={
            "message": "基金和ETF哪个更适合我？",
            "execute_agent": False,
        },
    )
    assert before.status_code == 200
    assert before.json()["evidence"]["financial_advisor_context"]["status"] == (
        "needs_profile"
    )

    confirmed = client.post(
        "/me/risk-profile/confirm",
        json={"version_no": draft.json()["version_no"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    after = client.post(
        "/me/chat",
        json={
            "message": "基金和ETF哪个更适合我？",
            "execute_agent": False,
        },
    )
    assert after.status_code == 200
    context = after.json()["evidence"]["financial_advisor_context"]
    assert context["status"] == "needs_profile"
    assert context["missing_fields"] == ["已有资产"]
    assert context["confirmed_risk_profile"]["version_no"] == 1

    with_holdings = client.post(
        "/me/chat",
        json={
            "message": "我目前主要持有银行存款，没有基金和股票，基金和ETF怎么选？",
            "execute_agent": False,
        },
    )
    assert with_holdings.status_code == 200
    completed_context = with_holdings.json()["evidence"][
        "financial_advisor_context"
    ]
    assert completed_context["status"] == "ready_for_conditional_guidance"
    assert completed_context["missing_fields"] == []


def test_confirmed_risk_profile_is_isolated_between_users(app) -> None:
    first = TestClient(app)
    second = TestClient(app)
    first_user = _create_user(first, "画像用户甲")
    _create_user(second, "画像用户乙")
    draft = first.put(
        "/me/risk-profile/draft",
        json={"base_version": 0, "answers": _complete_answers()},
    ).json()
    assert (
        first.post(
            "/me/risk-profile/confirm", json={"version_no": draft["version_no"]}
        ).status_code
        == 200
    )

    assert app.state.risk_profiles.confirmed_context(first_user["id"]) is not None
    second_packet = second.get("/me/risk-profile")
    assert second_packet.status_code == 200
    assert second_packet.json()["confirmed"] is None


def test_fund_and_risk_profile_frontend_preserves_explicit_user_boundary() -> None:
    root = Path(__file__).parents[1]
    frontend = (root / "app/static/demo.html").read_text(encoding="utf-8")
    script = (root / "app/static/qs-funds.js").read_text(encoding="utf-8")

    for fragment in (
        'id="fundComparisonForm"',
        'id="fundComparisonFirst"',
        'id="fundComparisonSecond"',
        'id="riskProfileForm"',
        'id="riskProfileConfirm"',
        'id="riskProfileProgressBar"',
        'id="riskProfileProgressText"',
        "回答 7 个问题",
        "保存并核对",
        "确认让 AI 使用",
        "场内成交价与基金净值会分开显示",
    ):
        assert fragment in frontend

    for fragment in (
        'api("/me/risk-profile")',
        'api("/me/risk-profile/draft"',
        'api("/me/risk-profile/confirm"',
        "state.riskProfileDirty",
        "riskProfileCompletion",
        "syncRiskProfileProgress",
        'fieldset.scrollIntoView({behavior: "smooth", block: "center"})',
        'ask.textContent = "去问金融顾问"',
        "请选择一个明确产品后再比较，系统不会静默替你选择",
        "让 AI 结合我的情况解读",
        "不要替我选择唯一产品",
    ):
        assert fragment in script

    advisor_function = script.split("function openRiskProfileAdvisor()", 1)[1].split(
        "function renderRiskProfileConfirmed", 1
    )[0]
    assert "startNewConversation" in advisor_function
    assert '$("chatInput").value' in advisor_function
    assert "更适合我优先比较" in advisor_function
    assert "已经知道的条件" in advisor_function
    assert "sendChat(" not in advisor_function
