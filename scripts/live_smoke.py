from __future__ import annotations

import json
from pathlib import Path
import tempfile

from app.db import Database
from app.providers.fundamentals import AShareFundamentalsProvider
from app.providers.market import (
    EastmoneySectorProvider,
    ResilientSectorProvider,
    SinaIndustrySectorProvider,
    YahooMarketProvider,
)
from app.services.financial_drivers import FinancialDriverAnalysisService


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qingshu-live-smoke-") as temp:
        root = Path(temp)
        database = Database(root / "smoke.db", root / "workspaces")
        database.initialize()
        yahoo = YahooMarketProvider(database, ttl_seconds=1)
        sectors_provider = ResilientSectorProvider(
            EastmoneySectorProvider(database, ttl_seconds=1),
            SinaIndustrySectorProvider(database, ttl_seconds=1),
        )

        results = {}
        try:
            history = yahoo.fetch_history("000001.SS", range_name="1mo")
            results["yahoo"] = {
                "status": "ok",
                "points": history["coverage"]["points"],
                "market_timestamp": history["market_timestamp"],
                "source": history["source"],
            }
        except Exception as exc:
            results["yahoo"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

        try:
            sectors = sectors_provider.fetch_hot_sectors(limit=5)
            results["a_share_sectors"] = {
                "status": "ok",
                "returned": sectors["coverage"]["returned"],
                "market_timestamp": sectors["market_timestamp"],
                "source": sectors["source"],
                "warnings": sectors["warnings"],
            }
        except Exception as exc:
            results["a_share_sectors"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

        try:
            statements = AShareFundamentalsProvider().fetch_statement_details(
                "000063.SZ", limit=8
            )
            database.upsert_financial_statement_details(statements["statements"])
            drivers = FinancialDriverAnalysisService(database).get_packet(
                "000063.SZ"
            )
            results["a_share_financial_drivers"] = {
                "status": "ok" if drivers["status"] == "available" else "failed",
                "statement_rows": len(statements["statements"]),
                "latest_report": (drivers.get("latest_period") or {}).get(
                    "report_date_name"
                ),
                "comparable_report": (drivers.get("comparable_period") or {}).get(
                    "report_date_name"
                ),
                "overall_label": drivers.get("overall_label"),
                "mechanical_drivers": len(
                    drivers.get("confirmed_mechanical_drivers") or []
                ),
                "plausible_clues": len(drivers.get("plausible_clues") or []),
            }
        except Exception as exc:
            results["a_share_financial_drivers"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

        print(json.dumps(results, ensure_ascii=False, indent=2))
        if all(value["status"] == "failed" for value in results.values()):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
