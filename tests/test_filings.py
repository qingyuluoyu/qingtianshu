from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from requests.exceptions import ProxyError

from app.db import Database
from app.providers.filings import AShareFilingProvider
from app.services.filings import (
    AShareFilingService,
    _is_explicit_company_explanation,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_provider_discovers_financial_report_and_fetches_all_text_pages():
    calls = []

    def http_get(url, **kwargs):
        calls.append((url, kwargs.get("params") or {}))
        if "security/ann" in url:
            return FakeResponse(
                {
                    "data": {
                        "list": [
                            {
                                "art_code": "AN2026Q1",
                                "title_ch": "中兴通讯:2026年一季度报告",
                                "display_time": "2026-04-24 17:52:06:910",
                                "columns": [{"column_name": "一季度报告全文"}],
                            },
                            {
                                "art_code": "AN-SUMMARY",
                                "title_ch": "中兴通讯:2025年年度报告摘要",
                                "display_time": "2026-03-06 20:47:24:612",
                                "columns": [{"column_name": "年度报告摘要"}],
                            },
                        ]
                    }
                }
            )
        page = kwargs["params"]["page_index"]
        contents = {
            1: (
                "2026年第一季度报告\n\n主要财务数据及财务指标变化说明。"
                "财务费用同比增加，主要因本期汇率波动产生汇兑"
            ),
            2: (
                "损失而上年同期为收益及净利息收入减少。"
                "本报告内容真实、准确、完整，不存在重大遗漏。"
                "董事会及全体董事对披露内容承担相应责任。"
            ),
        }
        return FakeResponse(
            {
                "data": {
                    "notice_title": "中兴通讯:2026年一季度报告",
                    "notice_date": "2026-04-25 00:00:00",
                    "notice_content": contents[page],
                    "page_size": 2,
                    "attach_url": "https://example.invalid/zte-q1.pdf",
                }
            }
        )

    provider = AShareFilingProvider(http_get=http_get)
    reports = provider.list_financial_reports("000063.SZ")
    document = provider.fetch_document(reports[0])

    assert len(reports) == 1
    assert reports[0]["report_period"] == "2026-03-31"
    assert document["document_type"] == "first_quarter"
    assert "净利息收入减少" in document["content_text"]
    assert (
        document["content_hash"]
        == hashlib.sha256(document["content_text"].encode("utf-8")).hexdigest()
    )
    assert [params.get("page_index") for _, params in calls if "content/ann" in _] == [
        1,
        2,
    ]


def test_provider_scans_later_announcement_page_for_financial_report():
    requested_pages = []

    def http_get(url, **kwargs):
        page = kwargs["params"]["page_index"]
        requested_pages.append(page)
        rows = (
            [
                {
                    "art_code": "AN-OTHER",
                    "title_ch": "中际旭创:关于股东减持的公告",
                    "display_time": "2026-08-05 18:40:15:607",
                    "columns": [{"column_name": "其他"}],
                }
            ]
            if page == 1
            else [
                {
                    "art_code": "AN2026Q1",
                    "title_ch": "中际旭创:2026年一季度报告",
                    "display_time": "2026-04-16 18:49:14:385",
                    "columns": [{"column_name": "一季度报告全文"}],
                }
            ]
        )
        return FakeResponse({"data": {"list": rows}})

    reports = AShareFilingProvider(http_get=http_get).list_financial_reports(
        "300308.SZ", limit=1
    )

    assert [report["article_code"] for report in reports] == ["AN2026Q1"]
    assert requested_pages == [1, 2]


def test_provider_excludes_financial_report_disclosure_notice():
    def http_get(url, **kwargs):
        del url, kwargs
        return FakeResponse(
            {
                "data": {
                    "list": [
                        {
                            "art_code": "AN-NOTICE",
                            "title_ch": "中际旭创:关于变更2026年第一季度报告预约披露时间的公告",
                            "display_time": "2026-04-16 18:49:14:418",
                            "columns": [{"column_name": "其他"}],
                        },
                        {
                            "art_code": "AN2026Q1",
                            "title_ch": "中际旭创:2026年一季度报告",
                            "display_time": "2026-04-16 18:49:14:385",
                            "columns": [{"column_name": "一季度报告全文"}],
                        },
                    ]
                }
            }
        )

    reports = AShareFilingProvider(http_get=http_get).list_financial_reports(
        "300308.SZ", limit=1
    )

    assert [report["article_code"] for report in reports] == ["AN2026Q1"]


def test_provider_falls_back_to_official_pdf_when_content_api_is_unreachable(
    monkeypatch,
):
    calls = []

    class PdfResponse:
        content = b"%PDF-1.7 test document"

        def raise_for_status(self):
            return None

    class StubConverter:
        def convert(self, *, raw, original_name):
            assert raw == PdfResponse.content
            assert original_name == "AN2026Q1.pdf"
            return SimpleNamespace(markdown="财报正文" * 40)

    def http_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if url == AShareFilingProvider.CONTENT_URL:
            raise ProxyError("content API is unavailable")
        return PdfResponse()

    monkeypatch.setattr(
        "app.providers.filings.DocumentConversionService",
        StubConverter,
        raising=False,
    )
    provider = AShareFilingProvider(http_get=http_get)

    document = provider.fetch_document(
        {
            "symbol": "300308.SZ",
            "article_code": "AN2026Q1",
            "title": "中际旭创:2026年一季度报告",
            "document_type": "first_quarter",
            "report_period": "2026-03-31",
            "notice_date": "2026-04-16",
            "published_at": "2026-04-16T18:49:14+08:00",
            "source": "company_filing",
            "source_url": "https://data.eastmoney.com/notices/detail/300308/AN2026Q1.html",
        }
    )

    assert calls[0][0] == AShareFilingProvider.CONTENT_URL
    assert calls[1][0] == "https://pdf.dfcfw.com/pdf/H2_AN2026Q1_1.pdf"
    assert document["content_text"] == "财报正文" * 40
    assert document["attach_url"] == "https://pdf.dfcfw.com/pdf/H2_AN2026Q1_1.pdf"
    assert document["warnings"] == ["正文 API 不可用，已从官方 PDF 提取财报全文"]


def test_filing_cause_extractor_rejects_inventory_table_and_policy_templates():
    assert not _is_explicit_company_explanation(
        "存货种类 确定可变现净值/剩余对价与将要发生的成本的具体依据 "
        "本期转回或转销存货跌价准备/合同履约成本减值准备的原因"
    )
    assert not _is_explicit_company_explanation(
        "资产负债表日，存货按成本与可变现净值孰低计量。"
    )
    assert _is_explicit_company_explanation(
        "资产减值损失同比增加，主要因本期存货跌价准备计提增加。"
    )


class StubFilingProvider:
    def list_financial_reports(self, symbol: str, limit: int = 3):
        return [
            {
                "symbol": symbol,
                "article_code": "AN-ZTE-2026Q1",
                "title": "中兴通讯:2026年一季度报告",
                "document_type": "first_quarter",
                "report_period": "2026-03-31",
                "notice_date": "2026-04-25",
                "published_at": "2026-04-25T00:00:00+08:00",
                "source": "company_filing",
                "source_url": "https://example.invalid/zte-q1",
            }
        ][:limit]

    def fetch_document(self, report):
        content = """
中兴通讯股份有限公司 2026 年第一季度报告

财务费用 340,974 (340,005) 200.28% 主要因本期汇率波动产生汇兑损失而上年同期为收益及净利息收入减少。

投资收益 405,786 3,750 10,720.96% 主要因本期联合营企业盈利而上年同期为损失及衍生品合约交割产生的收益增加。

经营活动产生的现金流量净额 (1,978,648) 1,851,253 (206.88%)。
""".strip()
        return {
            **report,
            "content_text": content,
            "attach_url": "https://example.invalid/zte-q1.pdf",
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "warnings": [],
            "fetched_at": "2026-07-21T04:00:00+00:00",
        }


def test_filing_service_persists_full_text_extracts_causes_and_indexes_knowledge(
    tmp_path: Path,
):
    database = Database(tmp_path / "workspaces")
    database.initialize()
    service = AShareFilingService(database, StubFilingProvider())

    result = service.refresh_symbol("000063.SZ")
    packet = service.get_packet("000063.SZ", report_period="2026-03-31")

    assert result["completed"] == 1
    document = database.get_filing_document("000063.SZ", "AN-ZTE-2026Q1")
    assert document is not None
    assert "汇兑损失" in document["content_text"]
    assert packet["status"] == "available"
    assert any(
        item["theme"] == "financial_expense_fx_interest"
        and item["classification"] == "explicit_company_explanation"
        and "净利息收入减少" in item["excerpt"]
        for item in packet["explicit_company_explanations"]
    )
    snapshot = database.latest_filing_evidence_snapshot(
        "000063.SZ", report_period="2026-03-31"
    )
    assert snapshot is not None
    documents = database.list_knowledge_documents(None, include_content=True)
    indexed = next(
        item
        for item in documents
        if item["source_key"] == "filing-evidence:000063.SZ:AN-ZTE-2026Q1"
    )
    assert "公司财报原文解释" not in indexed["content"]
    assert "汇兑损失" in indexed["content"]
    assert "不等于已经被独立数据证明" in indexed["content"]
