from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Any

from app.catalog import RESEARCH_TARGETS, normalize_symbol
from app.db import Database


class SecurityMasterService:
    """Resolve stable user-facing security identity from the local data master."""

    CACHE_SECONDS = 60.0

    def __init__(self, database: Database):
        self.database = database
        self._lock = Lock()
        self._loaded_at = 0.0
        self._data_version: str | None = None
        self._profiles: dict[str, dict[str, Any]] = {}

    def display_name(self, symbol: str, *fallbacks: Any) -> str:
        canonical = normalize_symbol(symbol)
        configured = str((RESEARCH_TARGETS.get(canonical) or {}).get("name") or "")
        profile_name = str((self.profile(canonical) or {}).get("name") or "")
        candidates = (
            (configured, profile_name, *fallbacks)
            if canonical.endswith((".SS", ".SZ"))
            else (configured, *fallbacks, profile_name)
        )
        for candidate in candidates:
            value = " ".join(str(candidate or "").split()).strip()
            if value and value.upper() not in {
                canonical,
                canonical.split(".", 1)[0],
            }:
                return value
        return canonical

    def profile(self, symbol: str) -> dict[str, Any] | None:
        canonical = normalize_symbol(symbol)
        self._refresh_if_needed()
        profile = self._profiles.get(canonical)
        if profile is not None:
            return dict(profile)
        target = RESEARCH_TARGETS.get(canonical)
        if not target:
            return None
        return {
            "symbol": canonical,
            "name": target.get("name") or canonical,
            "market": target.get("market"),
        }

    def universe_items(self) -> list[dict[str, Any]]:
        self._refresh_if_needed()
        output = {symbol: dict(item) for symbol, item in self._profiles.items()}
        for symbol, target in RESEARCH_TARGETS.items():
            canonical = normalize_symbol(symbol)
            output.setdefault(
                canonical,
                {
                    "symbol": canonical,
                    "name": target.get("name") or canonical,
                    "market": target.get("market"),
                    "industry": None,
                    "exchange": None,
                },
            )
        return list(output.values())

    def _refresh_if_needed(self) -> None:
        now = monotonic()
        if now - self._loaded_at < self.CACHE_SECONDS:
            return
        with self._lock:
            now = monotonic()
            if now - self._loaded_at < self.CACHE_SECONDS:
                return
            snapshot = self.database.latest_tushare_dataset_snapshot(
                "a_share_universe", "all"
            )
            version = str((snapshot or {}).get("data_version") or "") or None
            if version != self._data_version or not self._profiles:
                profiles: dict[str, dict[str, Any]] = {}
                for raw in ((snapshot or {}).get("payload") or {}).get("items", []):
                    if not isinstance(raw, dict):
                        continue
                    try:
                        canonical = normalize_symbol(
                            str(raw.get("symbol") or raw.get("ts_code") or "")
                        )
                    except ValueError:
                        continue
                    profiles[canonical] = {**raw, "symbol": canonical}
                self._profiles = profiles
                self._data_version = version
            self._loaded_at = now
