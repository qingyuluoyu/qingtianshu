from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

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
    database_path: Path
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
    sec_user_agent: str = "QingshuFinancialResearch/0.1 research@example.com"
    background_data_quality_seconds: int = 60
    session_ttl_days: int = 365
    session_cookie_secure: bool = False
    max_image_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 25_000_000
    max_document_upload_bytes: int = 2 * 1024 * 1024
    background_market_news_refresh_seconds: int = 600
    tushare_token: str = ""
    tushare_api_url: str = "https://teajoin.com"
    tushare_enabled: bool = False
    tushare_timeout_seconds: int = 20
    li_zong_universe_batch_size: int = 10
    li_zong_refresh_seconds: int = 30
    admin_api_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = _path_from_env("QINGSHU_DATA_DIR", DEFAULT_DATA_DIR)
        return cls(
            data_dir=data_dir,
            database_path=_path_from_env("QINGSHU_DB_PATH", data_dir / "qingshu.db"),
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
                    "DEFAULT_RESEARCH_SYMBOLS", "000063.SZ,300308.SZ,NVDA"
                ).split(",")
                if symbol.strip()
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
            max_image_upload_bytes=int(
                os.getenv("MAX_IMAGE_UPLOAD_BYTES", str(10 * 1024 * 1024))
            ),
            max_image_pixels=int(os.getenv("MAX_IMAGE_PIXELS", "25000000")),
            max_document_upload_bytes=int(
                os.getenv("MAX_DOCUMENT_UPLOAD_BYTES", str(2 * 1024 * 1024))
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
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
