from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4


FRONTEND = Path(__file__).resolve().parents[1]
REPOSITORY = FRONTEND.parent
RESOURCE_LABEL = "qingshu.e2e=react-production-baseline"


def run(
    *args: str,
    cwd: Path = REPOSITORY,
    env: dict[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def cleanup_run_resources(*, app: str, postgres: str, network: str) -> None:
    for container in (app, postgres):
        run("docker", "rm", "-f", container, check=False, capture=True)
    run("docker", "network", "rm", network, check=False, capture=True)


def wait_for_postgres(container: str, user: str, database: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = run(
            "docker",
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            container,
            capture=True,
        ).stdout.strip()
        if state in {"healthy", "running"}:
            ready = run(
                "docker",
                "exec",
                container,
                "pg_isready",
                "-U",
                user,
                "-d",
                database,
                capture=True,
                check=False,
            )
            if ready.returncode == 0:
                return
        if state in {"exited", "dead", "unhealthy"}:
            logs = run("docker", "logs", "--tail", "80", container, capture=True, check=False).stdout
            raise RuntimeError(f"PostgreSQL container failed: {state}\n{logs}")
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become healthy within 90 seconds")


def wait_for_app(container: str, base_url: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/health", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        state = run(
            "docker", "inspect", "--format", "{{.State.Status}}", container, capture=True
        ).stdout.strip()
        if state != "running":
            logs = run("docker", "logs", "--tail", "120", container, capture=True, check=False).stdout
            raise RuntimeError(f"FastAPI container failed: {state}\n{logs}")
        time.sleep(1)
    logs = run("docker", "logs", "--tail", "120", container, capture=True, check=False).stdout
    raise RuntimeError(f"FastAPI did not become ready within 120 seconds\n{logs}")


def assert_compose_path_is_host_independent() -> None:
    polluted = os.environ.copy()
    polluted["QINGSHU_FRONTEND_DIST_DIR"] = "C:/Program Files/Git/app/frontend/dist"
    rendered = run(
        "docker", "compose", "config", "--format", "json", env=polluted, capture=True
    ).stdout
    services = json.loads(rendered)["services"]
    resolved = {
        name: service.get("environment", {}).get("QINGSHU_FRONTEND_DIST_DIR")
        for name, service in services.items()
        if "QINGSHU_FRONTEND_DIST_DIR" in service.get("environment", {})
    }
    if not resolved or set(resolved.values()) != {"/app/frontend/dist"}:
        raise RuntimeError(f"Compose frontend path was polluted: {resolved}")
    print(f"[docker-e2e] compose_frontend_paths={resolved}")


def main() -> int:
    suffix = uuid4().hex[:10]
    image = f"qingshu-react-baseline-e2e:{suffix}"
    network = f"qingshu-react-e2e-{suffix}"
    postgres = f"qingshu-react-pg-{suffix}"
    app = f"qingshu-react-app-{suffix}"
    db_user = "qingshu_e2e"
    db_password = secrets.token_urlsafe(24)
    account = f"docker-e2e-{suffix}"
    password = f"Docker-E2E-{secrets.token_urlsafe(18)}"
    image_created = False
    run_label = f"qingshu.e2e.run={suffix}"

    try:
        assert_compose_path_is_host_independent()
        build_command = ["docker", "build"]
        if os.environ.get("QINGSHU_DOCKER_E2E_NO_CACHE", "1") != "0":
            build_command.append("--no-cache")
        run(*build_command, "--target", "e2e-runtime", "-t", image, ".")
        image_created = True
        run(
            "docker", "network", "create",
            "--label", RESOURCE_LABEL,
            "--label", run_label,
            network,
        )
        run(
            "docker", "run", "-d",
            "--name", postgres,
            "--network", network,
            "--label", RESOURCE_LABEL,
            "--label", run_label,
            "-e", "POSTGRES_DB=qingshu_auth_test",
            "-e", f"POSTGRES_USER={db_user}",
            "-e", f"POSTGRES_PASSWORD={db_password}",
            "postgres:17-alpine",
        )
        wait_for_postgres(postgres, db_user, "qingshu_auth_test")
        run(
            "docker", "run", "-d",
            "--name", app,
            "--network", network,
            "--label", RESOURCE_LABEL,
            "--label", run_label,
            "-p", "127.0.0.1::8000",
            "-e", f"QINGSHU_DATABASE_URL=postgresql://{db_user}:{db_password}@{postgres}:5432/qingshu_auth_test",
            "-e", "QINGSHU_LEGACY_ANONYMOUS_MODE=false",
            "-e", "BACKGROUND_JOBS_ENABLED=false",
            "-e", "BACKGROUND_WORKER_MODE=disabled",
            "-e", "HERMES_ENABLED=false",
            "-e", "SESSION_COOKIE_SECURE=false",
            image,
        )
        port_line = run("docker", "port", app, "8000/tcp", capture=True).stdout.strip()
        host_port = port_line.rsplit(":", 1)[-1]
        base_url = f"http://127.0.0.1:{host_port}"
        wait_for_app(app, base_url)

        runtime_contract = run(
            "docker",
            "exec",
            app,
            "sh",
            "-lc",
            "test -f /app/frontend/dist/index.html"
            " && find /app/frontend/dist/assets -type f | grep -Eq '\\.(js|css)$'"
            " && ! command -v node"
            " && ! command -v npm"
            " && test ! -d /app/node_modules"
            " && python -c \"from app.config import Settings; "
            "print('container_env=' + __import__('os').environ['QINGSHU_FRONTEND_DIST_DIR']); "
            "print('resolved_dist=' + str(Settings.from_env().frontend_dist_dir))\"",
            capture=True,
        ).stdout.strip()
        print(f"[docker-e2e] {runtime_contract.replace(chr(10), '; ')}")

        test_env = os.environ.copy()
        test_env.update(
            {
                "QINGSHU_PRODUCTION_E2E_BASE_URL": base_url,
                "QINGSHU_PRODUCTION_E2E_ACCOUNT": account,
                "QINGSHU_PRODUCTION_E2E_PHONE": "13900000001",
                "QINGSHU_PRODUCTION_E2E_PASSWORD": password,
                # Non-sensitive runtime identity used only for test diagnostics.
                # Database credentials, session cookies, and provider credentials
                # deliberately stay inside this isolated run.
                "QINGSHU_PRODUCTION_E2E_RUN_ID": suffix,
                "QINGSHU_PRODUCTION_E2E_IMAGE": image,
                "QINGSHU_PRODUCTION_E2E_MODE": "docker-production",
            }
        )
        playwright = FRONTEND / "node_modules" / ".bin" / (
            "playwright.cmd" if os.name == "nt" else "playwright"
        )
        result = run(
            str(playwright),
            "test",
            "--config=playwright.production.config.ts",
            cwd=FRONTEND,
            env=test_env,
            check=False,
        )
        return result.returncode
    finally:
        cleanup_run_resources(app=app, postgres=postgres, network=network)
        if image_created:
            run("docker", "image", "rm", "-f", image, check=False)
        print("[docker-e2e] isolated_database_and_runtime_resources_removed=true")


if __name__ == "__main__":
    raise SystemExit(main())
