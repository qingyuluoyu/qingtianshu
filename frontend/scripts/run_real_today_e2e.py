from __future__ import annotations

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


def test_database_url() -> str:
    configured = os.environ.get("QINGSHU_TEST_POSTGRES_URL", "").strip()
    if not configured:
        configured = str(dotenv_values(REPOSITORY / ".env").get("QINGSHU_DATABASE_URL") or "").strip()
        configured = configured.replace("postgresql+psycopg://", "postgresql://")
        parsed = urlsplit(configured)
        configured = urlunsplit((parsed.scheme, parsed.netloc, f"/{EXPECTED_DATABASE}", parsed.query, parsed.fragment))
    parsed = urlsplit(configured)
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"真实 E2E 只允许使用 {EXPECTED_DATABASE}，当前配置被拒绝")
    return configured


def schema_url(base_url: str, schema: str) -> str:
    parsed = urlsplit(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, quote_via=quote), parsed.fragment))


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
    base_url = test_database_url()
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
            "QINGSHU_APP_FACTORY_ONLY": "0",
            "QINGSHU_DATA_DIR": str(runtime_dir / "data"),
            "QINGSHU_WORKSPACE_ROOT": str(runtime_dir / "workspaces"),
            "QINGSHU_LEGACY_ANONYMOUS_MODE": "false",
            # This runner serves plain HTTP on loopback. Production Compose keeps
            # secure cookies enabled behind HTTPS ingress.
            "SESSION_COOKIE_SECURE": "false",
            "BACKGROUND_JOBS_ENABLED": "false",
            "BACKGROUND_WORKER_MODE": "disabled",
            "HERMES_ENABLED": "false",
            "VITE_PROXY_TARGET": f"http://127.0.0.1:{BACKEND_PORT}",
        })
        print(f"[real-e2e] database={EXPECTED_DATABASE}; isolated_schema={schema}")
        with log_path.open("wb") as backend_log:
            backend = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT), "--log-level", "warning"],
                cwd=REPOSITORY,
                env=env,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
            )
            wait_for_backend(backend, log_path)
            playwright = FRONTEND / "node_modules" / ".bin" / "playwright.cmd"
            result = subprocess.run(
                [str(playwright), "test", "--config=playwright.real.config.ts"],
                cwd=FRONTEND,
                env=env,
                check=False,
            )
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
