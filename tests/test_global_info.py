from __future__ import annotations

from app.providers.global_info import NasdaqCompanyNewsProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "rows": [
                    {
                        "title": "NVIDIA expands AI factory partnership",
                        "created": "Jul 20, 2026",
                        "primarysymbol": "bmy",
                        "related_symbols": ["bmy|stocks", "nvda|stocks"],
                        "url": "/articles/nvidia-ai-factory",
                        "publisher": "RTTNews",
                        "description": "A new AI infrastructure partnership was announced.",
                    },
                    {
                        "title": "After Hours Most Active for Jul 20, 2026: NVDA, AAPL, INTC",
                        "created": "Jul 20, 2026",
                        "primarysymbol": "nvda",
                        "related_symbols": ["nvda|stocks"],
                        "url": "/articles/after-hours-most-active",
                        "publisher": "Nasdaq",
                        "description": "NVDA appears in a broad market activity list.",
                    },
                    {
                        "title": "Unrelated article",
                        "created": "Jul 20, 2026",
                        "primarysymbol": "aapl",
                        "related_symbols": ["aapl|stocks"],
                        "url": "/articles/unrelated",
                        "publisher": "Other",
                        "description": "Not relevant.",
                    },
                    {
                        "title": "5 Semiconductor Stocks Poised to Outperform",
                        "created": "Jul 20, 2026",
                        "primarysymbol": "nvda",
                        "related_symbols": ["nvda|stocks"],
                        "url": "/articles/stock-picks",
                        "publisher": "Opinion Wire",
                        "description": "The list includes Nvidia.",
                    },
                    {
                        "title": "AI infrastructure spending accelerates",
                        "created": "Jul 20, 2026",
                        "primarysymbol": "nvda",
                        "related_symbols": ["nvda|stocks"],
                        "url": "/articles/generic-ai",
                        "publisher": "Opinion Wire",
                        "description": "Nvidia is discussed but not identified in the title.",
                    },
                ]
            }
        }


def test_nasdaq_news_provider_keeps_only_symbol_related_rows():
    provider = NasdaqCompanyNewsProvider(
        http_get=lambda *args, **kwargs: FakeResponse()
    )
    items = provider.fetch_company_news("NVDA", limit=10)
    assert len(items) == 1
    assert items[0]["symbol"] == "NVDA"
    assert items[0]["source"] == "Nasdaq News / RTTNews"
    assert items[0]["url"] == "https://www.nasdaq.com/articles/nvidia-ai-factory"
    assert items[0]["published_at"] == "2026-07-20T00:00:00-04:00"
