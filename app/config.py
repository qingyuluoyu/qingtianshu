from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path.home() / ".qingshu"


_INITIAL_ENV_KEYS = frozenset(os.environ)
_ENV_SOURCE_DIRS: dict[str, Path] = {}
_LOADED_ENV_VALUES: dict[str, str] = {}


def load_environment() -> tuple[Path, ...]:
    """Load portable configuration files without overriding process variables."""

    candidates: list[Path] = []
    explicit = str(os.getenv("QINGSHU_ENV_FILE") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    candidates.extend(
        [
            (Path.cwd() / ".env").resolve(),
            (PROJECT_ROOT / ".env").resolve(),
        ]
    )
    loaded: list[Path] = []
    for path in candidates:
        if path in loaded:
            continue
        values = dotenv_values(path) if path.is_file() else {}
        load_dotenv(path, override=False)
        for key in values:
            if key in _INITIAL_ENV_KEYS or key in _ENV_SOURCE_DIRS:
                continue
            _ENV_SOURCE_DIRS[key] = path.parent
            if key in os.environ:
                _LOADED_ENV_VALUES[key] = os.environ[key]
        loaded.append(path)
    return tuple(loaded)


LOADED_ENV_FILES = load_environment()


_DEPLOYMENT_ENVIRONMENTS = frozenset(
    {"development", "test", "staging", "production"}
)
_PLACEHOLDER_DATABASE_PASSWORDS = frozenset(
    {
        "change-me",
        "password",
        "postgres",
        "qingshu-local-only",
        "replace-with-a-long-random-password",
    }
)


def validate_deployment_environment(
    deployment_environment: str,
    *,
    database_url: str,
    session_cookie_secure: bool,
    sec_user_agent: str,
    admin_api_token: str,
) -> None:
    """Fail closed on unsafe staging/production configuration.

    Error messages intentionally contain configuration field names only. They
    must remain safe to emit during process startup without leaking secrets.
    """

    mode = str(deployment_environment or "").strip().lower()
    if mode not in _DEPLOYMENT_ENVIRONMENTS:
        raise ValueError(
            "QINGSHU_DEPLOYMENT_ENV must be development, test, staging, or production"
        )
    if mode in {"development", "test"}:
        return

    failures: list[str] = []
    normalized_url = database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    try:
        password = unquote(urlsplit(normalized_url).password or "").strip()
    except ValueError:
        password = ""
    normalized_password = password.casefold()
    if (
        not password
        or normalized_password in _PLACEHOLDER_DATABASE_PASSWORDS
        or "replace-with" in normalized_password
    ):
        failures.append("QINGSHU_DATABASE_URL")
    if not session_cookie_secure:
        failures.append("SESSION_COOKIE_SECURE")
    contact = str(sec_user_agent or "").strip().casefold()
    if (
        not contact
        or "research@example.com" in contact
        or "your-email" in contact
        or "@example." in contact
    ):
        failures.append("SEC_USER_AGENT")
    token = str(admin_api_token or "").strip()
    token_lower = token.casefold()
    if token and (len(token) < 32 or "replace-with" in token_lower):
        failures.append("QINGSHU_ADMIN_API_TOKEN")
    if failures:
        raise ValueError(
            f"unsafe {mode} configuration: {', '.join(failures)}"
        )


def _path_from_env(name: str, default: Path | str, *, command: bool = False) -> Path:
    raw = str(os.getenv(name, default)).strip()
    path = Path(raw).expanduser()
    if command and not path.is_absolute() and path.parent == Path("."):
        return path
    if path.is_absolute():
        return path.resolve()
    loaded_value = _LOADED_ENV_VALUES.get(name)
    base = (
        _ENV_SOURCE_DIRS.get(name, Path.cwd())
        if loaded_value is not None and raw == loaded_value
        else Path.cwd()
    )
    return (base / path).resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    workspace_root: Path
    hermes_bin: Path
    hermes_enabled: bool
    hermes_timeout_seconds: int
    market_cache_seconds: int
    sector_cache_seconds: int
    intraday_cache_seconds: int
    article_min_interval_hours: int
    article_max_per_24h: int
    background_jobs_enabled: bool
    background_market_refresh_seconds: int
    background_article_check_seconds: int
    background_info_refresh_seconds: int
    background_fundamentals_refresh_seconds: int
    background_research_refresh_seconds: int
    background_calibration_refresh_seconds: int
    background_use_hermes: bool
    default_a_share_symbols: tuple[str, ...]
    default_research_symbols: tuple[str, ...]
    default_fund_product_codes: tuple[str, ...] = (
        "510300",
        "510500",
        "159915",
        "110022",
        "000011",
        "000198",
    )
    background_fund_product_refresh_seconds: int = 1800
    sec_user_agent: str = "QingshuFinancialResearch/0.1 research@example.com"
    background_data_quality_seconds: int = 60
    session_ttl_days: int = 30
    session_cookie_secure: bool = False
    auth_rate_limit_per_source: int = 120
    auth_rate_limit_per_principal: int = 10
    auth_rate_limit_window_seconds: int = 60
    auth_rate_limit_max_keys: int = 4096
    auth_password_hash_concurrency: int = 2
    legacy_anonymous_mode: bool = False
    max_image_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 25_000_000
    max_document_upload_bytes: int = 20 * 1024 * 1024
    background_market_news_refresh_seconds: int = 600
    tushare_token: str = ""
    tushare_api_url: str = "https://teajoin.com"
    tushare_enabled: bool = False
    tushare_timeout_seconds: int = 20
    li_zong_universe_batch_size: int = 10
    li_zong_refresh_seconds: int = 30
    admin_api_token: str = ""
    database_url: str = ""
    background_worker_mode: str = "embedded"
    job_queue_poll_seconds: float = 1.0
    job_lease_seconds: int = 300
    job_max_attempts: int = 3
    job_retry_base_seconds: int = 10
    job_retry_max_seconds: int = 600
    job_worker_concurrency: int = 2
    job_worker_heartbeat_seconds: int = 10
    job_worker_stale_seconds: int = 45
    backup_dir: Path = Path("./backups")
    backup_max_age_seconds: int = 93600
    job_succeeded_retention_hours: int = 168
    job_failed_retention_hours: int = 720
    job_cancelled_retention_hours: int = 168
    background_run_completed_retention_hours: int = 720
    background_run_failed_retention_hours: int = 2160
    data_health_retention_hours: int = 720
    frontend_dist_dir: Path = PROJECT_ROOT / "frontend" / "dist"
    deployment_environment: str = "development"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = _path_from_env("QINGSHU_DATA_DIR", DEFAULT_DATA_DIR)
        database_url = os.getenv("QINGSHU_DATABASE_URL", "").strip()
        if not database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://")
        ):
            raise ValueError(
                "QINGSHU_DATABASE_URL is required and must use PostgreSQL"
            )
        deployment_environment = os.getenv(
            "QINGSHU_DEPLOYMENT_ENV", "development"
        ).strip().lower()
        worker_mode = os.getenv("BACKGROUND_WORKER_MODE", "embedded").strip().lower()
        if worker_mode not in {"embedded", "external", "disabled"}:
            raise ValueError(
                "BACKGROUND_WORKER_MODE must be embedded, external, or disabled"
            )
        settings = cls(
            data_dir=data_dir,
            workspace_root=_path_from_env(
                "QINGSHU_WORKSPACE_ROOT", data_dir / "workspaces"
            ),
            hermes_bin=_path_from_env("HERMES_BIN", "hermes", command=True),
            hermes_enabled=os.getenv("HERMES_ENABLED", "false").lower() in {"1", "true", "yes"},
            hermes_timeout_seconds=int(os.getenv("HERMES_TIMEOUT_SECONDS", "120")),
            market_cache_seconds=int(os.getenv("MARKET_CACHE_SECONDS", "300")),
            sector_cache_seconds=int(os.getenv("SECTOR_CACHE_SECONDS", "60")),
            intraday_cache_seconds=int(os.getenv("INTRADAY_CACHE_SECONDS", "20")),
            article_min_interval_hours=int(os.getenv("ARTICLE_MIN_INTERVAL_HOURS", "4")),
            article_max_per_24h=int(os.getenv("ARTICLE_MAX_PER_24H", "3")),
            background_jobs_enabled=os.getenv("BACKGROUND_JOBS_ENABLED", "true").lower()
            in {"1", "true", "yes"},
            background_market_refresh_seconds=int(
                os.getenv("BACKGROUND_MARKET_REFRESH_SECONDS", "30")
            ),
            background_article_check_seconds=int(
                os.getenv("BACKGROUND_ARTICLE_CHECK_SECONDS", "1800")
            ),
            background_info_refresh_seconds=int(
                os.getenv("BACKGROUND_INFO_REFRESH_SECONDS", "600")
            ),
            background_fundamentals_refresh_seconds=int(
                os.getenv("BACKGROUND_FUNDAMENTALS_REFRESH_SECONDS", "3600")
            ),
            background_research_refresh_seconds=int(
                os.getenv("BACKGROUND_RESEARCH_REFRESH_SECONDS", "1800")
            ),
            background_calibration_refresh_seconds=int(
                os.getenv("BACKGROUND_CALIBRATION_REFRESH_SECONDS", "21600")
            ),
            background_use_hermes=os.getenv("BACKGROUND_USE_HERMES", "false").lower()
            in {"1", "true", "yes"},
            default_a_share_symbols=tuple(
                symbol.strip().upper()
                for symbol in os.getenv(
                    "DEFAULT_A_SHARE_SYMBOLS", "600519.SS,300750.SZ,000001.SZ"
                ).split(",")
                if symbol.strip()
            ),
            default_research_symbols=tuple(
                symbol.strip().upper()
                for symbol in os.getenv(
                    "DEFAULT_RESEARCH_SYMBOLS",
                    "000063.SZ,300308.SZ,300750.SZ,NVDA",
                ).split(",")
                if symbol.strip()
            ),
            default_fund_product_codes=tuple(
                code.strip()
                for code in os.getenv(
                    "DEFAULT_FUND_PRODUCT_CODES",
                    "510300,510500,159915,110022,000011,000198",
                ).split(",")
                if code.strip()
            ),
            background_fund_product_refresh_seconds=max(
                300,
                int(os.getenv("BACKGROUND_FUND_PRODUCT_REFRESH_SECONDS", "1800")),
            ),
            sec_user_agent=os.getenv(
                "SEC_USER_AGENT",
                "QingshuFinancialResearch/0.1 research@example.com",
            ).strip(),
            background_data_quality_seconds=int(
                os.getenv("BACKGROUND_DATA_QUALITY_SECONDS", "60")
            ),
            session_ttl_days=int(os.getenv("SESSION_TTL_DAYS", "365")),
            session_cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower()
            in {"1", "true", "yes"},
            auth_rate_limit_per_source=max(
                1, int(os.getenv("AUTH_RATE_LIMIT_PER_SOURCE", "120"))
            ),
            auth_rate_limit_per_principal=max(
                1, int(os.getenv("AUTH_RATE_LIMIT_PER_PRINCIPAL", "10"))
            ),
            auth_rate_limit_window_seconds=max(
                1, int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))
            ),
            auth_rate_limit_max_keys=max(
                2, int(os.getenv("AUTH_RATE_LIMIT_MAX_KEYS", "4096"))
            ),
            auth_password_hash_concurrency=max(
                1, int(os.getenv("AUTH_PASSWORD_HASH_CONCURRENCY", "2"))
            ),
            legacy_anonymous_mode=os.getenv(
                "QINGSHU_LEGACY_ANONYMOUS_MODE", "false"
            ).lower()
            in {"1", "true", "yes"},
            max_image_upload_bytes=int(
                os.getenv("MAX_IMAGE_UPLOAD_BYTES", str(10 * 1024 * 1024))
            ),
            max_image_pixels=int(os.getenv("MAX_IMAGE_PIXELS", "25000000")),
            max_document_upload_bytes=int(
                os.getenv("MAX_DOCUMENT_UPLOAD_BYTES", str(20 * 1024 * 1024))
            ),
            background_market_news_refresh_seconds=int(
                os.getenv("BACKGROUND_MARKET_NEWS_REFRESH_SECONDS", "600")
            ),
            tushare_token=os.getenv("TUSHARE_TOKEN", "").strip(),
            tushare_api_url=os.getenv("TUSHARE_API_URL", "https://teajoin.com").strip().rstrip("/"),
            tushare_enabled=os.getenv(
                "TUSHARE_ENABLED",
                "true" if os.getenv("TUSHARE_TOKEN", "").strip() else "false",
            ).lower()
            in {"1", "true", "yes"},
            tushare_timeout_seconds=int(os.getenv("TUSHARE_TIMEOUT_SECONDS", "20")),
            li_zong_universe_batch_size=max(
                1, int(os.getenv("LI_ZONG_UNIVERSE_BATCH_SIZE", "10"))
            ),
            li_zong_refresh_seconds=max(
                10, int(os.getenv("LI_ZONG_REFRESH_SECONDS", "30"))
            ),
            admin_api_token=os.getenv("QINGSHU_ADMIN_API_TOKEN", "").strip(),
            database_url=database_url,
            background_worker_mode=worker_mode,
            job_queue_poll_seconds=max(
                0.1, float(os.getenv("JOB_QUEUE_POLL_SECONDS", "1"))
            ),
            job_lease_seconds=max(10, int(os.getenv("JOB_LEASE_SECONDS", "300"))),
            job_max_attempts=max(1, int(os.getenv("JOB_MAX_ATTEMPTS", "3"))),
            job_retry_base_seconds=max(
                1, int(os.getenv("JOB_RETRY_BASE_SECONDS", "10"))
            ),
            job_retry_max_seconds=max(
                1, int(os.getenv("JOB_RETRY_MAX_SECONDS", "600"))
            ),
            job_worker_concurrency=max(
                1, int(os.getenv("JOB_WORKER_CONCURRENCY", "2"))
            ),
            job_worker_heartbeat_seconds=max(
                1, int(os.getenv("JOB_WORKER_HEARTBEAT_SECONDS", "10"))
            ),
            job_worker_stale_seconds=max(
                5, int(os.getenv("JOB_WORKER_STALE_SECONDS", "45"))
            ),
            backup_dir=_path_from_env(
                "QINGSHU_BACKUP_DIR", data_dir / "backups"
            ),
            backup_max_age_seconds=max(
                60, int(os.getenv("QINGSHU_BACKUP_MAX_AGE_SECONDS", "93600"))
            ),
            job_succeeded_retention_hours=max(
                1, int(os.getenv("JOB_SUCCEEDED_RETENTION_HOURS", "168"))
            ),
            job_failed_retention_hours=max(
                1, int(os.getenv("JOB_FAILED_RETENTION_HOURS", "720"))
            ),
            job_cancelled_retention_hours=max(
                1, int(os.getenv("JOB_CANCELLED_RETENTION_HOURS", "168"))
            ),
            background_run_completed_retention_hours=max(
                1,
                int(
                    os.getenv(
                        "BACKGROUND_RUN_COMPLETED_RETENTION_HOURS", "720"
                    )
                ),
            ),
            background_run_failed_retention_hours=max(
                1,
                int(
                    os.getenv(
                        "BACKGROUND_RUN_FAILED_RETENTION_HOURS", "2160"
                    )
                ),
            ),
            data_health_retention_hours=max(
                1, int(os.getenv("DATA_HEALTH_RETENTION_HOURS", "720"))
            ),
            frontend_dist_dir=_path_from_env(
                "QINGSHU_FRONTEND_DIST_DIR", PROJECT_ROOT / "frontend" / "dist"
            ),
            deployment_environment=deployment_environment,
        )
        validate_deployment_environment(
            settings.deployment_environment,
            database_url=settings.database_url,
            session_cookie_secure=settings.session_cookie_secure,
            sec_user_agent=settings.sec_user_agent,
            admin_api_token=settings.admin_api_token,
        )
        return settings

    @property
    def operational_database_url(self) -> str:
        if not self.database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://")
        ):
            raise ValueError(
                "QINGSHU_DATABASE_URL is required and must use PostgreSQL"
            )
        return self.database_url

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
