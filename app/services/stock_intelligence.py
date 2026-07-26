from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Callable
from urllib.parse import quote_plus

from app.catalog import normalize_symbol
from app.config import Settings
from app.providers.llm_gateway import LLMGatewayClient, LLMGatewayError
from app.providers.market import ProviderError
from app.providers.market_news import GoogleNewsMarketProvider
from app.providers.tavily_search import TavilySearchClient
from app.utils import utc_now


class StockIntelligenceService:
    """Three-day industry intelligence snapshot for the stock score page."""

    def __init__(
        self,
        database: Any,
        profile_resolver: Callable[[str], dict[str, Any]],
        settings: Settings,
        industry_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self.database = database
        self.profile_resolver = profile_resolver
        self.settings = settings
        self.industry_resolver = industry_resolver
        self.search = TavilySearchClient(settings)
        self.fallback_search = GoogleNewsMarketProvider(
            timeout_seconds=min(12, settings.tavily_timeout_seconds)
        )
        self.gateway = LLMGatewayClient(settings)
        self.cache_seconds = max(
            3600, int(settings.stock_intelligence_cache_seconds)
        )

    def external_searches(self, symbol: str) -> dict[str, Any]:
        profile = self._profile(symbol)
        code, exchange = profile["symbol"].split(".", 1)
        keyword = f"{profile['name']} {code}"
        encoded = quote_plus(keyword)
        lixinger_market = {"SS": "sh", "SZ": "sz", "BJ": "bj"}.get(
            exchange, exchange.lower()
        )
        lixinger_slug = str(int(code)) if code.isdigit() else code.lower()
        return {
            "symbol": profile["symbol"],
            "name": profile["name"],
            "keyword": keyword,
            "items": [
                {
                    "id": "cninfo",
                    "title": "巨潮资讯公告",
                    "source": "巨潮资讯",
                    "category": "公告与财报",
                    "publishedAt": "关键词直达",
                    "url": (
                        "https://www.cninfo.com.cn/new/fulltextSearch"
                        f"?notautosubmit=&keyWord={encoded}"
                    ),
                },
                {
                    "id": "eastmoney",
                    "title": "东方财富资讯与研报",
                    "source": "东方财富",
                    "category": "资讯与研报",
                    "publishedAt": "关键词直达",
                    "url": f"https://so.eastmoney.com/web/s?keyword={encoded}",
                },
                {
                    "id": "10jqka",
                    "title": "同花顺个股资讯",
                    "source": "同花顺",
                    "category": "个股与行业资讯",
                    "publishedAt": "关键词直达",
                    "url": (
                        "https://search.10jqka.com.cn/search"
                        f"?tid=info&w={encoded}"
                    ),
                },
                {
                    "id": "cls",
                    "title": "财联社公司与行业资讯",
                    "source": "财联社",
                    "category": "快讯与深度",
                    "publishedAt": "关键词直达",
                    "url": f"https://www.cls.cn/searchPage?keyword={encoded}",
                },
                {
                    "id": "xueqiu",
                    "title": "雪球讨论与公司动态",
                    "source": "雪球",
                    "category": "投资者讨论",
                    "publishedAt": "关键词直达",
                    "url": f"https://xueqiu.com/k?q={encoded}",
                },
                {
                    "id": "lixinger",
                    "title": "理杏仁基本面与估值",
                    "source": "理杏仁",
                    "category": "基本面与估值",
                    "publishedAt": "个股直达",
                    "url": (
                        "https://www.lixinger.com/equity/company/detail/"
                        f"{lixinger_market}/{code}/{lixinger_slug}/profile"
                    ),
                },
                {
                    "id": "sina",
                    "title": "新浪财经新闻检索",
                    "source": "新浪财经",
                    "category": "财经新闻",
                    "publishedAt": "关键词直达",
                    "url": f"https://search.sina.com.cn/?c=news&q={encoded}",
                },
            ],
        }

    def curated_insights(
        self, symbol: str, *, force: bool = False
    ) -> dict[str, Any]:
        profile = self._profile(symbol)
        if self.industry_resolver is not None:
            try:
                resolved_industry = self.industry_resolver(profile["symbol"])
                if resolved_industry:
                    profile["industry"] = resolved_industry
            except Exception:
                pass
        industry = str(profile.get("industry") or profile["name"]).strip()
        cache_key = (
            "stock-intelligence:v3:industry:"
            f"{hashlib.sha1(industry.encode('utf-8')).hexdigest()[:12]}"
        )
        if not force:
            cached = self.database.get_cache(cache_key)
            if cached is not None:
                cached["symbol"] = profile["symbol"]
                cached["name"] = profile["name"]
                cached["cache"] = {
                    "state": "hit",
                    "refreshIntervalDays": 3,
                }
                return cached

        query = (
            f"{industry} 行业 最新动态 政策 供需 价格 竞争格局 "
            "重点公司公告 经营变量 风险"
        )
        search_packet = self.search.safe_search_target(
            target={"name": industry, "symbol": ""},
            question=query,
        )
        if search_packet.get("status") != "completed":
            try:
                search_industry = re.sub(
                    r"(申万|一级|二级|ⅰ|ⅱ|i{1,3}|行业)$",
                    "",
                    industry,
                    flags=re.I,
                ).strip()
                fallback = self.fallback_search.search(
                    f'"{profile["name"]}" {search_industry} 行业 when:90d',
                    label=f"{industry}行业",
                    limit=10,
                    marker=f"__INDUSTRY_{hashlib.sha1(industry.encode('utf-8')).hexdigest()[:12]}__",
                )
                search_packet = {
                    "provider": "google_news_rss",
                    "status": "completed",
                    "query": fallback.get("query"),
                    "searched_at": fallback.get("fetched_at"),
                    "results": [
                        {
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "content": item.get("title"),
                            "score": max(0.1, 1 - index * 0.05),
                            "published_date": item.get("published_at"),
                            "source_domain": item.get("source") or "Google News",
                        }
                        for index, item in enumerate(fallback.get("items") or [])
                    ],
                    "warning": "Tavily 未配置，已使用 Google News RSS 联网检索。",
                }
            except ProviderError:
                pass
        search_results = list(search_packet.get("results") or [])
        generated_at = utc_now()
        refresh_after = (
            datetime.now(timezone.utc) + timedelta(seconds=self.cache_seconds)
        ).isoformat(timespec="seconds")

        if search_packet.get("status") != "completed" or not search_results:
            return {
                "symbol": profile["symbol"],
                "name": profile["name"],
                "industry": industry,
                "status": search_packet.get("status") or "failed",
                "items": [],
                "generatedAt": generated_at,
                "refreshAfter": None,
                "refreshIntervalDays": 3,
                "source": "Tavily 行业搜索",
                "warning": search_packet.get("warning"),
                "search": self._search_summary(search_packet),
                "cache": {"state": "miss", "refreshIntervalDays": 3},
            }

        items, selection_method = self._select_five(
            profile=profile,
            industry=industry,
            results=search_results,
            strict_relevance=search_packet.get("provider") != "tavily",
        )
        packet = {
            "symbol": profile["symbol"],
            "name": profile["name"],
            "industry": industry,
            "status": "completed",
            "items": items[:5],
            "generatedAt": generated_at,
            "fetched_at": generated_at,
            "refreshAfter": refresh_after,
            "refreshIntervalDays": 3,
            "source": (
                "Tavily 联网搜索 + 大模型筛选"
                if search_packet.get("provider") == "tavily"
                else "Google News RSS 联网搜索 + 大模型筛选"
            ),
            "selectionMethod": selection_method,
            "warning": search_packet.get("warning"),
            "search": self._search_summary(search_packet),
            "cache": {"state": "fresh", "refreshIntervalDays": 3},
        }
        self.database.put_cache(
            cache_key,
            packet,
            ttl_seconds=self.cache_seconds,
        )
        return packet

    def _select_five(
        self,
        *,
        profile: dict[str, Any],
        industry: str,
        results: list[dict[str, Any]],
        strict_relevance: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        selected_indexes: list[int] = []
        generated: dict[int, dict[str, str]] = {}
        relevant_indexes = {
            index
            for index, item in enumerate(results)
            if self._is_industry_relevant(
                item,
                industry=industry,
                company_name=str(profile.get("name") or ""),
            )
        }
        if self.gateway.enabled:
            sources = [
                {
                    "index": index,
                    "title": str(item.get("title") or "")[:180],
                    "content": str(item.get("content") or "")[:650],
                    "domain": item.get("source_domain"),
                    "published_date": item.get("published_date"),
                }
                for index, item in enumerate(results[:12])
            ]
            prompt = (
                f"从以下联网来源中，为{industry}行业筛选最多5条"
                "未来三天最值得投资研究者关注的行业信息。优先政策、供需、价格、竞争格局、"
                "重点公司经营变化和明确风险；去掉重复、营销软文和仅讲股价涨跌的内容。"
                "不得补充来源没有的事实。只返回JSON："
                '{"items":[{"source_index":0,"type":"政策/供需/竞争/公司/风险",'
                '"title":"不超过36字","summary":"不超过90字，说明为什么值得关注"}]}。'
                f"\n来源：{json.dumps(sources, ensure_ascii=False)}"
            )
            try:
                answer, _ = self.gateway.complete(
                    prompt=prompt,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout_seconds=min(
                        90, self.settings.llm_gateway_timeout_seconds
                    ),
                )
                parsed = self._parse_json(answer)
                for item in list(parsed.get("items") or []):
                    if not isinstance(item, dict):
                        continue
                    try:
                        index = int(item.get("source_index"))
                    except (TypeError, ValueError):
                        continue
                    if (
                        index < 0
                        or index >= len(results)
                        or index in selected_indexes
                        or (strict_relevance and index not in relevant_indexes)
                    ):
                        continue
                    selected_indexes.append(index)
                    generated[index] = {
                        "type": str(item.get("type") or "行业关注")[:12],
                        "title": str(item.get("title") or "")[:80],
                        "summary": str(item.get("summary") or "")[:220],
                    }
                    if len(selected_indexes) == 5:
                        break
            except (LLMGatewayError, ValueError, TypeError, json.JSONDecodeError):
                selected_indexes = []
                generated = {}

        for index, _ in sorted(
            enumerate(results),
            key=lambda pair: float(pair[1].get("score") or 0),
            reverse=True,
        ):
            if strict_relevance and index not in relevant_indexes:
                continue
            if index not in selected_indexes:
                selected_indexes.append(index)
            if len(selected_indexes) == 5:
                break

        items: list[dict[str, Any]] = []
        for rank, index in enumerate(selected_indexes[:5], start=1):
            source = results[index]
            ai_copy = generated.get(index) or {}
            title = ai_copy.get("title") or str(source.get("title") or "行业信息")
            summary = ai_copy.get("summary") or str(source.get("content") or "")
            items.append(
                {
                    "id": hashlib.sha1(
                        str(source.get("url") or index).encode("utf-8")
                    ).hexdigest()[:12],
                    "type": ai_copy.get("type") or "行业关注",
                    "title": title[:100],
                    "summary": re.sub(r"\s+", " ", summary).strip()[:260],
                    "source": source.get("source_domain") or "联网来源",
                    "publishedAt": source.get("published_date") or "近期",
                    "url": source.get("url"),
                    "priority": "high" if rank == 1 else "normal",
                    "isTop": rank == 1,
                }
            )
        method = "llm" if generated else "tavily_relevance"
        return items, method

    @staticmethod
    def _is_industry_relevant(
        item: dict[str, Any],
        *,
        industry: str,
        company_name: str,
    ) -> bool:
        text = (
            f"{item.get('title') or ''} {item.get('content') or ''}"
        ).casefold()
        normalized = re.sub(
            r"(申万|一级|二级|ⅰ|ⅱ|i{1,3}|行业|相关|服务|制造)$",
            "",
            industry.casefold().strip(),
        )
        terms = {
            term
            for term in re.findall(r"[\u4e00-\u9fff]{2,8}|[a-z0-9]{3,}", normalized)
            if term not in {"相关", "服务", "制造"}
        }
        alias_groups = {
            "游戏": {"游戏", "手游", "电竞", "版号", "网游"},
            "互联网": {"互联网", "平台经济", "网络游戏", "在线服务"},
            "传媒": {"传媒", "游戏", "影视", "广告", "出版"},
            "电池": {"电池", "锂电", "储能", "动力电池"},
            "白酒": {"白酒", "酒企", "酒业"},
            "半导体": {"半导体", "芯片", "晶圆", "封测"},
        }
        for marker, aliases in alias_groups.items():
            if marker in normalized:
                terms.update(aliases)
        if company_name:
            terms.add(company_name.casefold())
        return any(term and term in text for term in terms)

    def _profile(self, symbol: str) -> dict[str, Any]:
        profile = dict(self.profile_resolver(normalize_symbol(symbol)) or {})
        normalized = str(profile.get("symbol") or normalize_symbol(symbol))
        return {
            **profile,
            "symbol": normalized,
            "name": str(profile.get("name") or normalized),
        }

    def _search_summary(self, packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": packet.get("provider") or "tavily",
            "status": packet.get("status"),
            "query": packet.get("query"),
            "searchedAt": packet.get("searched_at"),
            "sourceCount": len(packet.get("results") or []),
            "skill": self.search.skill_metadata(),
        }

    @staticmethod
    def _parse_json(answer: str) -> dict[str, Any]:
        text = answer.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
        if fenced:
            text = fenced.group(1).strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("大模型未返回JSON对象")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("大模型JSON格式不正确")
        return parsed
