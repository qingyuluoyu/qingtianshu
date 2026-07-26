from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd

from app.config import Settings

try:
    import tushare as ts
except ImportError:  # pragma: no cover - exercised only before dependency install
    ts = None


class TushareProviderError(RuntimeError):
    """Raised when the configured Tushare-compatible service cannot be used."""


class TushareClient:
    """Small, secret-safe wrapper around the Tushare Pro SDK."""

    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://teajoin.com",
        timeout_seconds: int = 20,
    ) -> None:
        if ts is None:
            raise TushareProviderError("未安装 tushare 依赖")
        if not token.strip():
            raise TushareProviderError("未配置 TUSHARE_TOKEN")

        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._circuit_lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        try:
            ts.set_token(token)
            self.pro = ts.pro_api(token, timeout=self.timeout_seconds)
            # teajoin.com exposes the Tushare Pro protocol at its root URL.
            self.pro._DataApi_token = token
            self.pro._DataApi__http_url = self.api_url
        except Exception as exc:
            raise TushareProviderError(
                f"Tushare 客户端初始化失败：{type(exc).__name__}"
            ) from exc

    @classmethod
    def from_settings(cls, settings: Settings) -> "TushareClient":
        return cls(
            settings.tushare_token,
            api_url=settings.tushare_api_url,
            timeout_seconds=settings.tushare_timeout_seconds,
        )

    def query(self, api_name: str, **params: Any) -> pd.DataFrame:
        """Call one Tushare endpoint without ever including the token in errors."""
        with self._circuit_lock:
            if self._circuit_open_until > time.monotonic():
                raise TushareProviderError(
                    "Tushare 数据源暂时熔断，请稍后重试"
                )
        endpoint = getattr(self.pro, api_name, None)
        if endpoint is None or not callable(endpoint):
            raise TushareProviderError(f"Tushare 不支持接口：{api_name}")
        try:
            result = endpoint(**params)
        except Exception as exc:
            self._record_failure()
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 调用失败：{type(exc).__name__}"
            ) from exc
        self._record_success()
        if isinstance(result, pd.DataFrame):
            return result
        if result is None:
            return pd.DataFrame()
        try:
            return pd.DataFrame(result)
        except Exception as exc:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 返回格式无法解析：{type(exc).__name__}"
            ) from exc

    def _record_success(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.CIRCUIT_FAILURE_THRESHOLD:
                self._circuit_open_until = (
                    time.monotonic() + self.CIRCUIT_COOLDOWN_SECONDS
                )

    @staticmethod
    def to_tushare_symbol(symbol: str) -> str:
        """Translate the app's Yahoo-style Shanghai suffix to Tushare's suffix."""
        value = symbol.strip().upper()
        if value.endswith(".SS"):
            return value[:-3] + ".SH"
        return value

    @staticmethod
    def from_tushare_symbol(symbol: str) -> str:
        """Translate a Tushare symbol into the app's canonical symbol format."""
        value = symbol.strip().upper()
        if value.endswith(".SH"):
            return value[:-3] + ".SS"
        return value

    def stock_basic(self, **params: Any) -> pd.DataFrame:
        return self.query("stock_basic", **params)

    def trade_cal(self, **params: Any) -> pd.DataFrame:
        return self.query("trade_cal", **params)

    def daily_basic(self, **params: Any) -> pd.DataFrame:
        return self.query("daily_basic", **params)

    def fina_indicator(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "fina_indicator",
            ts_code=self.to_tushare_symbol(ts_code),
            **params,
        )

    def adj_factor(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        **params: Any,
    ) -> pd.DataFrame:
        return self.query(
            "adj_factor",
            **self._symbol_date_params(
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                extra=params,
            ),
        )

    def stk_limit(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        **params: Any,
    ) -> pd.DataFrame:
        return self.query(
            "stk_limit",
            **self._symbol_date_params(
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                extra=params,
            ),
        )

    def top10_holders(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "top10_holders",
            ts_code=self.to_tushare_symbol(ts_code),
            **params,
        )

    def top10_floatholders(
        self, *, ts_code: str, **params: Any
    ) -> pd.DataFrame:
        return self.query(
            "top10_floatholders",
            ts_code=self.to_tushare_symbol(ts_code),
            **params,
        )

    def income(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "income", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def balancesheet(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "balancesheet", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def cashflow(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "cashflow", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def forecast(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "forecast", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def express(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "express", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def disclosure_date(self, *, ts_code: str, **params: Any) -> pd.DataFrame:
        return self.query(
            "disclosure_date", ts_code=self.to_tushare_symbol(ts_code), **params
        )

    def index_daily(
        self,
        *,
        ts_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        **params: Any,
    ) -> pd.DataFrame:
        return self.query(
            "index_daily",
            ts_code=self.to_tushare_symbol(ts_code),
            **{
                key: value
                for key, value in {
                    "start_date": start_date,
                    "end_date": end_date,
                    **params,
                }.items()
                if value is not None
            },
        )

    def daily(
        self,
        *,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return self.query(
            "daily",
            **self._symbol_date_params(
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            ),
        )

    def _symbol_date_params(
        self,
        *,
        ts_code: str | None,
        trade_date: str | None,
        start_date: str | None,
        end_date: str | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "ts_code": self.to_tushare_symbol(ts_code) if ts_code else None,
                "trade_date": trade_date,
                "start_date": start_date,
                "end_date": end_date,
                **(extra or {}),
            }.items()
            if value is not None
        }
