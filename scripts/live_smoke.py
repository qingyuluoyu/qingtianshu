from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from app.config import Settings
from app.db import Database
from app.providers.fundamentals import AShareFundamentalsProvider
from app.providers.market import (
    EastmoneySectorProvider,
    ResilientSectorProvider,
    SinaIndustrySectorProvider,
    YahooMarketProvider,
)
from app.services.financial_drivers import FinancialDriverAnalysisService


@contextmanager
def isolated_postgres_schema(database_url: str) -> Iterator[str]:
    schema = "live_smoke_" + uuid4().hex
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    isolated_url = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield isolated_url
    finally:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def main() -> None:
    database_url = Settings.from_env().database_url
    with (
        isolated_postgres_schema(database_url) as isolated_url,
        tempfile.TemporaryDirectory(prefix="qingshu-live-smoke-") as temp,
    ):
        root = Path(temp)
        database = Database(root / "workspaces", isolated_url)
        try:
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
                results["yahoo"] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }

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
        finally:
            database.close()


if __name__ == "__main__":
    main()
