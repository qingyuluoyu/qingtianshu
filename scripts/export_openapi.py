from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql


EXPECTED_DATABASE = "qingshu_auth_test"


def require_test_database_url(database_url: str) -> str:
    normalized = database_url.strip().replace(
        "postgresql+psycopg://", "postgresql://"
    )
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.path.lstrip("/") != EXPECTED_DATABASE
    ):
        raise RuntimeError(
            f"OpenAPI export only allows the isolated {EXPECTED_DATABASE} database"
        )
    return normalized


def isolated_schema_url(database_url: str, schema: str) -> str:
    parsed = urlsplit(require_test_database_url(database_url))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, quote_via=quote),
            parsed.fragment,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the current FastAPI contract for the locked frontend build."
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    base_url = require_test_database_url(
        os.environ.get("QINGSHU_TEST_POSTGRES_URL")
        or os.environ.get("QINGSHU_DATABASE_URL", "")
    )
    schema = f"openapi_{uuid4().hex}"
    with psycopg.connect(base_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    app = None
    os.environ["QINGSHU_APP_FACTORY_ONLY"] = "1"
    os.environ["QINGSHU_DATABASE_URL"] = isolated_schema_url(base_url, schema)
    os.environ["BACKGROUND_JOBS_ENABLED"] = "false"
    os.environ["BACKGROUND_WORKER_MODE"] = "disabled"
    os.environ["HERMES_ENABLED"] = "false"
    try:
        with tempfile.TemporaryDirectory(prefix="qingshu-openapi-") as runtime:
            os.environ["QINGSHU_DATA_DIR"] = runtime
            os.environ["QINGSHU_WORKSPACE_ROOT"] = str(Path(runtime) / "workspaces")
            from app.main import create_app

            app = create_app()
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 0
    finally:
        try:
            if app is not None:
                try:
                    app.state.background.stop()
                finally:
                    try:
                        app.state.event_broker.close()
                    finally:
                        try:
                            app.state.background.job_store.close()
                        finally:
                            app.state.database.close()
        finally:
            with psycopg.connect(base_url) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )


if __name__ == "__main__":
    raise SystemExit(main())
