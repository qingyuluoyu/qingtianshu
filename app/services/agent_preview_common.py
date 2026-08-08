from __future__ import annotations

from typing import Any


def fmt(value: Any, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def money(value: Any, currency: str | None) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    amount = float(value)
    if currency == "USD":
        if abs(amount) >= 1_000_000_000_000:
            return f"{fmt(amount / 1_000_000_000_000)} 万亿美元"
        return f"{fmt(amount / 100_000_000)} 亿美元"
    if currency == "CNY":
        return f"{fmt(amount / 100_000_000)} 亿元"
    return f"{fmt(amount)} {currency or ''}".strip()
