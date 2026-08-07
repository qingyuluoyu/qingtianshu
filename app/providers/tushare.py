from __future__ import annotations

import json
from typing import Any

import pandas as pd
import requests

from app.config import Settings


class TushareProviderError(RuntimeError):
    """Raised when the configured Tushare-compatible service cannot be used."""


class TushareProviderTimeout(TushareProviderError):
    """The licensed provider did not respond within the configured bound."""


class TushareClient:
    """Secret-safe client for the TeaJoin Tushare-compatible HTTPS protocol."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://teajoin.com",
        timeout_seconds: int = 20,
        http_post: Any = requests.post,
    ) -> None:
        if not token.strip():
            raise TushareProviderError("未配置 TUSHARE_TOKEN")

        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._token = token.strip()
        self._http_post = http_post

    @classmethod
    def from_settings(cls, settings: Settings) -> "TushareClient":
        return cls(
            settings.tushare_token,
            api_url=settings.tushare_api_url,
            timeout_seconds=settings.tushare_timeout_seconds,
        )

    def query(self, api_name: str, **params: Any) -> pd.DataFrame:
        """Call one Tushare endpoint without ever including the token in errors."""
        request_params = dict(params)
        fields = str(request_params.pop("fields", ""))
        request_params.setdefault("ts_type_name", self.api_url)
        request = {
            "api_name": api_name,
            "token": self._token,
            "params": request_params,
            "fields": fields,
        }
        try:
            response = self._http_post(
                f"{self.api_url}/{api_name}",
                json=request,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise TushareProviderTimeout(
                f"Tushare 接口 {api_name} 在 {self.timeout_seconds}s 内未响应"
            ) from exc
        except requests.RequestException as exc:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 请求失败：{type(exc).__name__}"
            ) from exc
        try:
            payload = response.json()
        except (AttributeError, ValueError, json.JSONDecodeError) as exc:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 返回了无法解析的响应"
            ) from exc
        if not isinstance(payload, dict):
            raise TushareProviderError(f"Tushare 接口 {api_name} 返回格式无效")
        if payload.get("code") != 0:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 返回业务错误 code={payload.get('code')}"
            )
        data = payload.get("data") or {}
        fields_value = data.get("fields") if isinstance(data, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(fields_value, list) or not isinstance(items, list):
            raise TushareProviderError(f"Tushare 接口 {api_name} 返回数据格式无效")
        try:
            return pd.DataFrame(items, columns=fields_value)
        except Exception as exc:
            raise TushareProviderError(
                f"Tushare 接口 {api_name} 返回数据无法解析：{type(exc).__name__}"
            ) from exc

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
