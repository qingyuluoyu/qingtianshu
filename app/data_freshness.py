from __future__ import annotations

from typing import Any, Mapping


def attach_data_freshness(
    payload: Mapping[str, Any], *, default_granularity: str
) -> dict[str, Any]:
    """Attach one presentation-safe freshness contract to provider output."""
    normalized = dict(payload)
    granularity = str(normalized.get("data_granularity") or default_granularity)
    is_stale = bool(normalized.get("is_stale"))
    provider_status = str(normalized.get("status") or "available")
    freshness_status = (
        "unavailable"
        if provider_status == "unavailable"
        else "stale"
        if is_stale
        else "fresh"
    )
    normalized["data_granularity"] = granularity
    normalized["is_stale"] = is_stale
    normalized["data_freshness"] = {
        "status": freshness_status,
        "granularity": granularity,
        "market_timestamp": normalized.get("market_timestamp"),
        "fetched_at": normalized.get("fetched_at"),
    }
    return normalized
