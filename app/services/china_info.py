from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.providers.china_info import AShareInformationProvider
from app.utils import utc_now


POSITIVE_TERMS = (
    "利好",
    "增持",
    "回购",
    "提价",
    "超预期",
    "上涨",
    "反弹",
    "突破",
    "创新高",
    "盈利",
    "中标",
    "增长",
    "看多",
)
NEGATIVE_TERMS = (
    "利空",
    "减持",
    "亏损",
    "下跌",
    "暴雷",
    "处罚",
    "调查",
    "风险",
    "违约",
    "下修",
    "不及预期",
    "看空",
    "跌停",
)


class ChinaInformationService:
    def __init__(self, database: Database, provider: AShareInformationProvider):
        self.database = database
        self.provider = provider

    def refresh_symbol(self, symbol: str) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        if not canonical.endswith((".SS", ".SZ")):
            raise ValueError("只支持 A 股证券的信息刷新")
        warnings = []
        collected: dict[str, list[dict[str, Any]]] = {
            "announcement": [],
            "news": [],
            "social": [],
        }
        fetchers = (
            ("announcement", self.provider.fetch_announcements),
            ("news", self.provider.fetch_company_news),
            ("social", self.provider.fetch_guba_posts),
        )
        for category, fetcher in fetchers:
            try:
                collected[category] = fetcher(canonical)
                self.database.upsert_news_items(collected[category])
            except Exception as exc:
                warnings.append(f"{category} 数据源失败：{type(exc).__name__}")
        sentiment = score_social_sentiment(canonical, collected["social"], warnings)
        saved_sentiment = self.database.save_sentiment_snapshot(sentiment)
        return {
            "symbol": canonical,
            "refreshed_at": utc_now(),
            "counts": {key: len(value) for key, value in collected.items()},
            "sentiment": saved_sentiment,
            "warnings": warnings,
        }

    def get_packet(self, symbol: str, refresh_max_age_seconds: int = 300) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        sentiment = self.database.latest_sentiment(canonical)
        should_refresh = sentiment is None
        if sentiment is not None:
            created = datetime.fromisoformat(sentiment["created_at"])
            should_refresh = datetime.now(timezone.utc) - created.astimezone(timezone.utc) > timedelta(
                seconds=refresh_max_age_seconds
            )
        refresh_result = None
        if should_refresh:
            refresh_result = self.refresh_symbol(canonical)
            sentiment = refresh_result["sentiment"]
        return {
            "symbol": canonical,
            "generated_at": utc_now(),
            "announcements": self.database.list_news(
                canonical, limit=8, categories=("announcement",)
            ),
            "news": self.database.list_news(canonical, limit=12, categories=("news",)),
            "social_posts": self.database.list_news(
                canonical, limit=12, categories=("social",)
            ),
            "sentiment": sentiment,
            "refresh": refresh_result,
            "methodology": [
                "公司公告作为最高优先级事实源。",
                "新浪个股资讯作为媒体事件源，需要回看原文。",
                "东方财富股吧只作为低可信零售情绪样本。",
                "情绪分数由公开关键词、互动权重和样本量确定性计算，不是涨跌预测。",
            ],
        }

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted(set(symbols)):
            try:
                results.append({"status": "ok", **self.refresh_symbol(symbol)})
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {
            "requested": len(set(symbols)),
            "completed": sum(item["status"] == "ok" for item in results),
            "results": results,
        }


def score_social_sentiment(
    symbol: str,
    posts: list[dict[str, Any]],
    source_warnings: list[str] | None = None,
) -> dict[str, Any]:
    positive_count = negative_count = neutral_count = 0
    positive_weight = negative_weight = neutral_weight = 0.0
    positive_examples = []
    negative_examples = []
    for post in posts:
        title = post.get("title") or ""
        engagement = max(0.0, float(post.get("engagement") or 0))
        weight = 1.0 + min(3.0, math.log10(1.0 + engagement))
        positive_hits = sum(term in title for term in POSITIVE_TERMS)
        negative_hits = sum(term in title for term in NEGATIVE_TERMS)
        if positive_hits > negative_hits:
            positive_count += 1
            positive_weight += weight
            if len(positive_examples) < 5:
                positive_examples.append(title)
        elif negative_hits > positive_hits:
            negative_count += 1
            negative_weight += weight
            if len(negative_examples) < 5:
                negative_examples.append(title)
        else:
            neutral_count += 1
            neutral_weight += weight
    total_weight = positive_weight + negative_weight + neutral_weight
    score = (positive_weight - negative_weight) / total_weight if total_weight else 0.0
    score = round(score, 4)
    if score >= 0.35:
        band = "偏多"
    elif score >= 0.12:
        band = "轻微偏多"
    elif score <= -0.35:
        band = "偏空"
    elif score <= -0.12:
        band = "轻微偏空"
    else:
        band = "中性或混合"
    sample_size = len(posts)
    if sample_size >= 25 and not source_warnings:
        confidence = "medium"
    elif sample_size >= 10:
        confidence = "low_to_medium"
    else:
        confidence = "low"
    return {
        "symbol": symbol,
        "score": score,
        "band": band,
        "confidence": confidence,
        "sample_size": sample_size,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "method": "keyword_engagement_weighted_v1",
        "evidence": {
            "positive_weight": round(positive_weight, 3),
            "negative_weight": round(negative_weight, 3),
            "neutral_weight": round(neutral_weight, 3),
            "positive_examples": positive_examples,
            "negative_examples": negative_examples,
            "source_warnings": source_warnings or [],
            "caveat": "社区表达存在噪声、反讽和操纵风险；该分数不能单独用于价格预测。",
        },
        "created_at": utc_now(),
    }
