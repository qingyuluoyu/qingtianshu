from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.config import Settings
from app.db import Database
from app.services.agent import AgentService
from app.services.analysis import MarketAnalysisService
from app.utils import utc_now


class MarketPulseArticleService:
    def __init__(
        self,
        database: Database,
        analysis: MarketAnalysisService,
        agent: AgentService,
        settings: Settings,
    ):
        self.database = database
        self.analysis = analysis
        self.agent = agent
        self.settings = settings
        self.editor_user = database.ensure_system_editor()

    def generate(
        self,
        model_tier: str = "economy",
        execute_agent: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        market_brief = self.analysis.market_brief()
        quality = self._quality(market_brief)
        fingerprint = self._fingerprint(market_brief)
        latest = self.database.latest_article(self.editor_user["id"], "market_pulse")

        if quality["score"] < quality["threshold"]:
            return {
                "decision": "withheld",
                "reason": "证据质量未达到发布门槛",
                "quality": quality,
                "market_brief": market_brief,
            }

        if not force and latest is not None:
            latest_time = datetime.fromisoformat(latest["created_at"])
            minimum = timedelta(hours=self.settings.article_min_interval_hours)
            if datetime.now(timezone.utc) - latest_time < minimum:
                return {
                    "decision": "suppressed",
                    "reason": f"距离上一篇不足 {self.settings.article_min_interval_hours} 小时",
                    "quality": quality,
                    "article": latest,
                }
            if latest["fingerprint"] == fingerprint:
                return {
                    "decision": "suppressed",
                    "reason": "市场结构指纹未发生足够变化",
                    "quality": quality,
                    "article": latest,
                }

        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        count = self.database.count_articles_since(
            self.editor_user["id"], "market_pulse", since
        )
        if not force and count >= self.settings.article_max_per_24h:
            return {
                "decision": "suppressed",
                "reason": f"已达到 24 小时 {self.settings.article_max_per_24h} 篇上限",
                "quality": quality,
                "article": latest,
            }

        title = self._title(market_brief)
        evidence = {
            "type": "market_pulse_article",
            "generated_at": utc_now(),
            "article_title": title,
            "market_brief": market_brief,
            "article_policy": {
                "quality": quality,
                "fingerprint": fingerprint,
                "minimum_interval_hours": self.settings.article_min_interval_hours,
                "maximum_per_24h": self.settings.article_max_per_24h,
                "forced_for_demo": force,
            },
        }
        run = self.agent.run(
            user=self.editor_user,
            intent="market_pulse_article",
            message="生成一篇高密度、低频、可追溯的实时行情文章。",
            evidence=evidence,
            model_tier=model_tier,
            execute_agent=execute_agent,
        )
        summary = self._summary(run["answer"])
        article = self.database.create_article(
            user_id=self.editor_user["id"],
            kind="market_pulse",
            title=title,
            summary=summary,
            body=run["answer"],
            status=run["status"],
            fingerprint=fingerprint,
            evidence=evidence,
            run_id=run["id"],
        )
        return {
            "decision": "published",
            "reason": "通过质量、频率和结构变化门槛",
            "quality": quality,
            "article": article,
            "run": run,
        }

    def list_articles(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self._public_article(item)
            for item in self.database.list_articles(self.editor_user["id"], limit=limit)
        ]

    @staticmethod
    def _public_article(article: dict[str, Any]) -> dict[str, Any]:
        item = dict(article)
        body = str(item.get("body") or "")
        marker = "## 数据边界"
        if marker in body:
            body = body.split(marker, 1)[0].rstrip()
            body += (
                "\n\n## 数据说明\n"
                "本文只描述已发生的指数与板块结构，不外推下一交易日方向。"
                "关键行情可能存在正常传输延迟，阅读时以页面标注时间为准。"
            )
        item["body"] = body
        for key in ("evidence", "user_id", "fingerprint", "run_id"):
            item.pop(key, None)
        return item

    @staticmethod
    def _quality(market_brief: dict[str, Any]) -> dict[str, Any]:
        indices = market_brief.get("indices", [])
        available = [item for item in indices if item.get("status") == "available"]
        index_ratio = len(available) / len(indices) if indices else 0.0
        sectors = market_brief.get("hot_sectors", {}).get("sectors", [])
        sector_ratio = min(len(sectors) / 5, 1.0)
        fresh_items = [item for item in available if not item.get("is_stale")]
        freshness_ratio = len(fresh_items) / len(available) if available else 0.0
        sector_meta = market_brief.get("hot_sectors", {})
        if sectors and not sector_meta.get("is_stale"):
            sector_freshness_ratio = 1.0 if sector_meta.get("market_timestamp") else 0.5
        else:
            sector_freshness_ratio = 0.0
        score = round(
            0.65 * index_ratio
            + 0.15 * sector_ratio
            + 0.1 * freshness_ratio
            + 0.1 * sector_freshness_ratio,
            3,
        )
        return {
            "score": score,
            "threshold": 0.7,
            "index_coverage_ratio": round(index_ratio, 3),
            "sector_coverage_ratio": round(sector_ratio, 3),
            "freshness_ratio": round(freshness_ratio, 3),
            "sector_freshness_ratio": round(sector_freshness_ratio, 3),
        }

    @staticmethod
    def _fingerprint(market_brief: dict[str, Any]) -> str:
        indices = []
        for item in market_brief.get("indices", []):
            value = item.get("metrics", {}).get("return_1d_pct")
            bucket = round(value * 2) / 2 if isinstance(value, (int, float)) else None
            indices.append([item.get("symbol"), bucket])
        sectors = [
            item.get("code") for item in market_brief.get("hot_sectors", {}).get("sectors", [])[:5]
        ]
        stable = {
            "market_state": market_brief.get("market_state", {}).get("label"),
            "indices": indices,
            "top_sectors": sectors,
        }
        return hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _title(market_brief: dict[str, Any]) -> str:
        state = market_brief.get("market_state", {}).get("label", "数据待确认")
        sectors = market_brief.get("hot_sectors", {}).get("sectors", [])
        if sectors:
            name = sectors[0]["name"]
            label = name if name.endswith(("行业", "板块", "概念")) else f"{name}板块"
            return f"市场脉冲｜主要指数{state}，{label}涨幅靠前"
        return f"市场脉冲｜主要指数{state}，结构变化仍需确认"

    @staticmethod
    def _summary(body: str) -> str:
        paragraphs = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return (paragraphs[0] if paragraphs else body.strip())[:240]
