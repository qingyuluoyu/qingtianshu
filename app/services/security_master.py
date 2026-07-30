from __future__ import annotations

import re
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
        self._unique_name_index: dict[str, str] = {}

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

    def symbols_mentioned_in(self, message: str) -> list[str]:
        """Resolve unambiguous full security names mentioned in natural language.

        The chat router already handles codes, tickers, configured aliases and
        watchlist names.  This method adds the missing production path for an
        arbitrary A-share full name from the local security master, so a user
        can ask about a stock without first adding it to a watchlist or knowing
        its code.  Short/generic names and duplicate names are deliberately not
        guessed; the search UI remains the clarification path for ambiguity.
        """

        folded_message = self._fold_name(message)
        if not folded_message:
            return []
        self._refresh_if_needed()
        candidates: list[tuple[int, int, str]] = []
        for folded_name, symbol in self._unique_name_index.items():
            start = folded_message.find(folded_name)
            if start < 0:
                continue
            candidates.append((start, -len(folded_name), symbol))
        output: list[str] = []
        for _, _, symbol in sorted(candidates):
            if symbol not in output:
                output.append(symbol)
        return output

    @staticmethod
    def _fold_name(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "")).casefold()

    @classmethod
    def _eligible_routing_name(cls, value: Any) -> str | None:
        normalized = " ".join(str(value or "").split()).strip()
        folded = cls._fold_name(normalized)
        if len(folded) < 3:
            return None
        if folded.isdigit():
            return None
        return folded

    def _rebuild_name_index(self) -> None:
        names: dict[str, set[str]] = {}
        profiles = dict(self._profiles)
        for symbol, target in RESEARCH_TARGETS.items():
            canonical = normalize_symbol(symbol)
            profiles.setdefault(
                canonical,
                {
                    "symbol": canonical,
                    "name": target.get("name") or canonical,
                },
            )
        for symbol, profile in profiles.items():
            folded_name = self._eligible_routing_name(profile.get("name"))
            if folded_name is None:
                continue
            names.setdefault(folded_name, set()).add(symbol)
        self._unique_name_index = {
            name: next(iter(symbols))
            for name, symbols in names.items()
            if len(symbols) == 1
        }

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
                self._rebuild_name_index()
            self._loaded_at = now
