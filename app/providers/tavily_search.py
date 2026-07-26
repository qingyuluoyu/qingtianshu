from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import Settings
from app.utils import utc_now


class TavilySearchError(RuntimeError):
    """Raised when a configured Tavily request cannot be completed."""


class TavilySearchClient:
    """Server-side Tavily search driven by the project-owned Tavily skill."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.tavily_enabled and self.settings.tavily_api_key)

    def skill_metadata(self) -> dict[str, Any] | None:
        skill_file = (
            self.settings.tavily_skill_path
            / "skills"
            / "tavily-search"
            / "SKILL.md"
        )
        if not skill_file.is_file():
            return None
        skill_text = skill_file.read_text(encoding="utf-8")
        name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", skill_text)
        name = name_match.group(1).strip("\"' ") if name_match else "tavily-search"
        digest_inputs = [skill_text]
        reference_file = (
            self.settings.tavily_skill_path
            / "skills"
            / "tavily-best-practices"
            / "references"
            / "search.md"
        )
        if reference_file.is_file():
            digest_inputs.append(reference_file.read_text(encoding="utf-8"))
        digest = hashlib.sha256(
            "\n\n".join(digest_inputs).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "active": True,
            "name": name,
            "digest": digest,
            "path": str(skill_file.relative_to(self.settings.tavily_skill_path)),
        }

    def search_target(
        self,
        *,
        target: dict[str, str],
        question: str,
    ) -> dict[str, Any]:
        query = self._build_query(target, question)
        if not self.enabled:
            return {
                "provider": "tavily",
                "status": "not_configured",
                "query": query,
                "searched_at": None,
                "results": [],
                "warning": "Tavily API Key 未配置，本次仅使用本地证据。",
            }

        depth = self.settings.tavily_search_depth
        if depth not in {"ultra-fast", "fast", "basic", "advanced"}:
            depth = "basic"
        max_results = max(1, min(int(self.settings.tavily_max_results), 12))
        payload: dict[str, Any] = {
            "query": query,
            "search_depth": depth,
            "max_results": max_results,
            "topic": "finance",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "auto_parameters": False,
            "safe_search": True,
        }
        if depth in {"advanced", "fast"}:
            payload["chunks_per_source"] = 3

        try:
            response = requests.post(
                f"{self.settings.tavily_base_url.rstrip('/')}/search",
                headers={
                    "Authorization": f"Bearer {self.settings.tavily_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.tavily_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TavilySearchError(f"Tavily request failed: {exc}") from exc
        if response.status_code >= 400:
            raise TavilySearchError(
                f"Tavily HTTP {response.status_code}: {response.text[:240]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise TavilySearchError("Tavily returned non-JSON body") from exc

        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for raw in data.get("results") or []:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            content = re.sub(
                r"\s+", " ", str(raw.get("content") or "")
            ).strip()
            try:
                score = round(float(raw.get("score") or 0), 4)
            except (TypeError, ValueError):
                score = 0.0
            results.append(
                {
                    "title": str(raw.get("title") or parsed.netloc).strip()[:240],
                    "url": url,
                    "content": content[:1600],
                    "score": score,
                    "published_date": raw.get("published_date"),
                    "source_domain": parsed.netloc.lower(),
                }
            )

        return {
            "provider": "tavily",
            "status": "completed",
            "query": query,
            "searched_at": utc_now(),
            "results": results,
            "request_id": data.get("request_id"),
            "response_time": data.get("response_time"),
            "warning": (
                None
                if results
                else "Tavily 未返回可用来源，本次仅使用本地证据。"
            ),
        }

    def safe_search_target(
        self,
        *,
        target: dict[str, str],
        question: str,
    ) -> dict[str, Any]:
        try:
            return self.search_target(target=target, question=question)
        except TavilySearchError:
            return {
                "provider": "tavily",
                "status": "failed",
                "query": self._build_query(target, question),
                "searched_at": utc_now(),
                "results": [],
                "warning": "联网检索暂时不可用，本次继续使用本地证据。",
            }

    def snapshot_summary(
        self, searches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        statuses = [str(item.get("status") or "") for item in searches]
        source_count = sum(len(item.get("results") or []) for item in searches)
        if searches and all(status == "completed" for status in statuses):
            status = "completed"
        elif "completed" in statuses:
            status = "partial"
        elif "failed" in statuses:
            status = "failed"
        else:
            status = "not_configured"
        return {
            "provider": "tavily",
            "status": status,
            "configured": status != "not_configured",
            "source_count": source_count,
            "skill": self.skill_metadata(),
        }

    @staticmethod
    def _build_query(target: dict[str, str], question: str) -> str:
        name = str(target.get("name") or "").strip()
        symbol = str(target.get("symbol") or "").strip()
        query = (
            f"{name} {symbol} {str(question or '').strip()} "
            "最新公告 财报 关键经营变量 行业竞争 风险"
        )
        return re.sub(r"\s+", " ", query).strip()[:380]
