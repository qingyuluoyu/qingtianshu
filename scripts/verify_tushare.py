from __future__ import annotations

from app.config import Settings
from app.providers.tushare import TushareClient, TushareProviderError


def main() -> int:
    settings = Settings.from_env()
    if not settings.tushare_enabled:
        print("Tushare 未启用：请检查 TUSHARE_ENABLED 和 TUSHARE_TOKEN。")
        return 2

    try:
        client = TushareClient.from_settings(settings)
        frame = client.daily(
            ts_code="000001.SZ",
            start_date="20260101",
            end_date="20260110",
        )
    except TushareProviderError as exc:
        print(f"Tushare 连通性校验失败：{exc}")
        return 1

    print(f"Tushare 连通性校验通过：{len(frame)} 行")
    if not frame.empty:
        print(f"字段：{', '.join(str(column) for column in frame.columns)}")
        print(f"最新交易日：{frame.iloc[0].get('trade_date', '未知')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
