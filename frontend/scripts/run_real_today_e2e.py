from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from psycopg import sql
from dotenv import dotenv_values


FRONTEND = Path(__file__).resolve().parents[1]
REPOSITORY = FRONTEND.parent
BACKEND_PORT = 8011
EXPECTED_DATABASE = "qingshu_auth_test"
DEFAULT_MARKET_SNAPSHOT_DATABASE = "qingshu_prod"
HERMES_ACCEPTANCE_SYMBOL = "000063.SZ"
HERMES_ACCEPTANCE_PEERS = ("600498.SS", "000938.SZ", "301165.SZ")
REQUIRED_HERMES_EVIDENCE_TABLES = {
    "market_bars",
    "valuation_snapshots",
    "financial_periods",
    "financial_statement_details",
}


def playwright_executable(platform_name: str | None = None) -> Path:
    executable = "playwright.cmd" if (platform_name or os.name) == "nt" else "playwright"
    return FRONTEND / "node_modules" / ".bin" / executable


def npm_executable(platform_name: str | None = None) -> str:
    return "npm.cmd" if (platform_name or os.name) == "nt" else "npm"


def playwright_command(*, production_dist: bool, spec: str | None = None) -> list[str]:
    config = (
        "playwright.production.config.ts"
        if production_dist
        else "playwright.real.config.ts"
    )
    command = [str(playwright_executable()), "test", f"--config={config}"]
    if spec:
        command.append(spec)
    return command


def require_hermes_route() -> tuple[str, str]:
    provider = os.environ.get("HERMES_ECONOMY_PROVIDER", "").strip()
    model = os.environ.get("HERMES_ECONOMY_MODEL", "").strip()
    if not provider or not model:
        raise RuntimeError(
            "--hermes requires explicit HERMES_ECONOMY_PROVIDER and "
            "HERMES_ECONOMY_MODEL"
        )
    return provider, model


def test_database_url() -> str:
    configured = os.environ.get("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not configured:
        configured = str(dotenv_values(REPOSITORY / ".env").get("QINGSHU_DATABASE_URL") or "").strip()
        configured = configured.replace("postgresql+psycopg://", "postgresql://")
        parsed = urlsplit(configured)
        configured = urlunsplit((parsed.scheme, parsed.netloc, f"/{EXPECTED_DATABASE}", parsed.query, parsed.fragment))
    parsed = urlsplit(configured)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.netloc:
        raise RuntimeError(
            "真实 E2E 需要完整 PostgreSQL 测试库 URL；"
            "请设置 QINGSHU_TEST_POSTGRES_URL，不能使用本地文件路径"
        )
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"真实 E2E 只允许使用 {EXPECTED_DATABASE}，当前配置被拒绝")
    return configured


def schema_url(base_url: str, schema: str) -> str:
    parsed = urlsplit(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, quote_via=quote), parsed.fragment))


def market_snapshot_database_url(base_url: str) -> str:
    configured = os.environ.get("QINGSHU_E2E_MARKET_SNAPSHOT_URL", "").strip()
    if configured:
        configured = configured.replace("postgresql+psycopg://", "postgresql://")
    else:
        parsed = urlsplit(base_url)
        configured = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"/{DEFAULT_MARKET_SNAPSHOT_DATABASE}",
                parsed.query,
                parsed.fragment,
            )
        )
    parsed = urlsplit(configured)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.netloc:
        raise RuntimeError("真实 E2E 市场快照源必须使用完整 PostgreSQL URL")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    read_only_option = "-cdefault_transaction_read_only=on"
    existing_options = query.get("options", "").strip()
    query["options"] = (
        existing_options
        if "default_transaction_read_only=on" in existing_options
        else f"{existing_options} {read_only_option}".strip()
    )
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, quote_via=quote),
            parsed.fragment,
        )
    )


def validate_market_snapshot_database(url: str) -> None:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM tushare_dataset_snapshots
            WHERE data_status = 'stable'
              AND dataset IN ('a_share_universe', 'stock_basic', 'daily', 'daily_basic')
            """
        ).fetchone()
    if row is None or int(row[0]) == 0:
        raise RuntimeError("真实 E2E 市场快照源没有可用的稳定 A 股数据")


def public_research_evidence_seed_specs(
    symbol: str = HERMES_ACCEPTANCE_SYMBOL,
) -> tuple[tuple[str, str, tuple[object, ...]], ...]:
    research_symbols = [symbol, *HERMES_ACCEPTANCE_PEERS]
    return (
        ("market_cache", "cache_key LIKE %s", (f"yahoo:{symbol}:%",)),
        ("market_bars", "symbol = %s", (symbol,)),
        (
            "valuation_snapshots",
            "symbol = ANY(%s)",
            (research_symbols,),
        ),
        (
            "financial_periods",
            "symbol = ANY(%s)",
            (research_symbols,),
        ),
        (
            "financial_statement_details",
            "symbol = ANY(%s)",
            (research_symbols,),
        ),
        ("filing_documents", "symbol = %s", (symbol,)),
        ("filing_evidence_snapshots", "symbol = %s", (symbol,)),
        (
            "business_segment_rows",
            "symbol = ANY(%s)",
            (research_symbols,),
        ),
        (
            "business_structure_snapshots",
            "symbol = ANY(%s)",
            (research_symbols,),
        ),
        ("shareholder_structure_snapshots", "symbol = %s", (symbol,)),
        ("analyst_expectation_snapshots", "symbol = %s", (symbol,)),
        ("event_timeline_snapshots", "symbol = %s", (symbol,)),
        (
            "news_items",
            "symbol = %s ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT 320",
            (symbol,),
        ),
        (
            "sentiment_snapshots",
            "symbol = %s ORDER BY created_at DESC LIMIT 1",
            (symbol,),
        ),
        ("peer_operating_snapshots", "symbol = %s", (symbol,)),
        ("outlook_calibrations", "symbol = %s", (symbol,)),
    )


def seed_public_research_evidence(
    source_url: str,
    target_url: str,
    *,
    symbol: str = HERMES_ACCEPTANCE_SYMBOL,
) -> dict[str, int]:
    """Copy public, symbol-scoped evidence into the isolated acceptance schema.

    Authentication, conversations, formal judgments, drafts, tasks, and user
    workspaces deliberately remain absent. The source connection is read-only;
    the copied evidence preserves its original timestamps and provenance.
    """

    copied: dict[str, int] = {}
    with psycopg.connect(source_url) as source, psycopg.connect(target_url) as target:
        for table, where_clause, parameters in public_research_evidence_seed_specs(
            symbol
        ):
            select_query = sql.SQL("SELECT * FROM {} WHERE ").format(
                sql.Identifier(table)
            ) + sql.SQL(where_clause)
            cursor = source.execute(select_query, parameters)
            rows = cursor.fetchall()
            columns = [column.name for column in cursor.description or ()]
            if rows and columns:
                insert_query = sql.SQL(
                    "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING"
                ).format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                target.cursor().executemany(insert_query, rows)
            copied[table] = len(rows)

    missing = sorted(
        table for table in REQUIRED_HERMES_EVIDENCE_TABLES if copied.get(table, 0) == 0
    )
    if missing:
        raise RuntimeError(
            "真实 Hermes 验收缺少必要的公开研究证据：" + ", ".join(missing)
        )
    return copied


def wait_for_backend(process: subprocess.Popen[bytes], log_path: Path) -> None:
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"FastAPI 启动失败（退出码 {process.returncode}）：\n{tail}")
        try:
            with urlopen(f"http://127.0.0.1:{BACKEND_PORT}/openapi.json", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("FastAPI 在 75 秒内未就绪")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=12)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated real frontend E2E.")
    parser.add_argument(
        "--spec",
        help="Optional Playwright spec path, for example e2e-real/advisor-real.spec.ts",
    )
    parser.add_argument(
        "--production-dist",
        action="store_true",
        help="Build the React production bundle and test it through FastAPI instead of Vite.",
    )
    parser.add_argument(
        "--hermes",
        action="store_true",
        help="Enable a real Hermes model call using an explicitly configured economy route.",
    )
    args = parser.parse_args()
    hermes_route = require_hermes_route() if args.hermes else None
    base_url = test_database_url()
    market_snapshot_url = market_snapshot_database_url(base_url)
    validate_market_snapshot_database(market_snapshot_url)
    if args.production_dist:
        subprocess.run(
            [npm_executable(), "run", "build"],
            cwd=FRONTEND,
            env=os.environ.copy(),
            check=True,
        )
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise RuntimeError("React production build did not produce frontend/dist/index.html")
    schema = f"e2e_today_{uuid4().hex}"
    runtime_dir = Path(tempfile.mkdtemp(prefix="qingshu-today-real-e2e-"))
    log_path = runtime_dir / "fastapi.log"
    backend: subprocess.Popen[bytes] | None = None
    created = False
    try:
        with psycopg.connect(base_url) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        created = True
        env = os.environ.copy()
        env.update({
            "QINGSHU_DATABASE_URL": schema_url(base_url, schema),
            "QINGSHU_MARKET_SNAPSHOT_DATABASE_URL": market_snapshot_url,
            "QINGSHU_APP_FACTORY_ONLY": "0",
            "QINGSHU_DATA_DIR": str(runtime_dir / "data"),
            "QINGSHU_WORKSPACE_ROOT": str(runtime_dir / "workspaces"),
            "QINGSHU_LEGACY_ANONYMOUS_MODE": "false",
            "BACKGROUND_JOBS_ENABLED": "false",
            "BACKGROUND_WORKER_MODE": "disabled",
            "HERMES_ENABLED": "true" if args.hermes else "false",
            "VITE_PROXY_TARGET": f"http://127.0.0.1:{BACKEND_PORT}",
        })
        if args.hermes:
            env.setdefault("HERMES_TIMEOUT_SECONDS", "180")
        if args.production_dist:
            env.update({
                "QINGSHU_FRONTEND_DIST_DIR": str(FRONTEND / "dist"),
                "SESSION_COOKIE_SECURE": "false",
                "QINGSHU_PRODUCTION_E2E_BASE_URL": f"http://127.0.0.1:{BACKEND_PORT}",
                "QINGSHU_PRODUCTION_E2E_ACCOUNT": f"local-production-{uuid4().hex[:10]}",
                "QINGSHU_PRODUCTION_E2E_PHONE": "13900000001",
                "QINGSHU_PRODUCTION_E2E_PASSWORD": f"Local-Production-{uuid4().hex}",
                "QINGSHU_PRODUCTION_E2E_HERMES": "true" if args.hermes else "false",
            })
        print(
            f"[real-e2e] database={EXPECTED_DATABASE}; isolated_schema={schema}; "
            f"market_snapshot_database={urlsplit(market_snapshot_url).path.lstrip('/')}; "
            f"frontend_mode={'production-dist' if args.production_dist else 'vite'}; "
            f"hermes_route={hermes_route[0] + '/' + hermes_route[1] if hermes_route else 'disabled'}"
        )
        with log_path.open("wb") as backend_log:
            backend = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT), "--log-level", "warning"],
                cwd=REPOSITORY,
                env=env,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
            )
            wait_for_backend(backend, log_path)
            if args.hermes:
                copied = seed_public_research_evidence(
                    market_snapshot_url,
                    schema_url(base_url, schema),
                )
                print(
                    "[real-e2e] public_research_evidence_seeded="
                    + ",".join(
                        f"{table}:{count}"
                        for table, count in copied.items()
                        if count
                    )
                )
            result = subprocess.run(
                playwright_command(
                    production_dist=args.production_dist,
                    spec=args.spec,
                ),
                cwd=FRONTEND,
                env=env,
                check=False,
            )
            if result.returncode != 0:
                backend_log.flush()
                print("[real-e2e] fastapi_log_tail_begin")
                print(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
                print("[real-e2e] fastapi_log_tail_end")
            return result.returncode
    finally:
        if backend is not None:
            stop_process(backend)
        if created:
            with psycopg.connect(base_url) as connection:
                connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            print(f"[real-e2e] isolated_schema_removed={schema}; temporary_user_removed=true")
        shutil.rmtree(runtime_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
