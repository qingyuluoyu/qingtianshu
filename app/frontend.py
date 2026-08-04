from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException
from fastapi.responses import FileResponse


INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}
ASSET_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
}

SPA_ROUTE_NAMES = frozenset({"react_page", "react_router_fallback"})


def registered_backend_prefixes(routes: Iterable[Any]) -> frozenset[str]:
    """Derive protected backend namespaces from the routes FastAPI registered."""
    prefixes: set[str] = set()
    for route in routes:
        path = getattr(route, "path", "")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or getattr(route, "name", None) in SPA_ROUTE_NAMES
            or not getattr(route, "methods", None)
        ):
            continue
        first_static_segment = next(
            (
                part
                for part in path.split("/")
                if part and not (part.startswith("{") and part.endswith("}"))
            ),
            None,
        )
        if first_static_segment:
            prefixes.add(f"/{first_static_segment}")
    return frozenset(prefixes)


def _accepts_html(accept: str) -> bool:
    for item in accept.split(","):
        media_type, *parameters = (part.strip().lower() for part in item.split(";"))
        if media_type != "text/html":
            continue
        quality = next(
            (parameter.split("=", 1)[1] for parameter in parameters if parameter.startswith("q=")),
            "1",
        )
        try:
            return float(quality) > 0
        except ValueError:
            return False
    return False


def should_serve_spa(
    *, method: str, path: str, accept: str, backend_prefixes: frozenset[str]
) -> bool:
    """Return true only for browser navigation misses that belong to React Router."""
    if method.upper() not in {"GET", "HEAD"} or not _accepts_html(accept):
        return False

    normalized = "/" + path.lstrip("/")
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return True
    if Path(segments[-1]).suffix:
        return False
    if segments[0].lower() == "api" or segments[0].lower().startswith("api-"):
        return False
    return not any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in backend_prefixes
    )


def react_index(dist_dir: Path) -> FileResponse:
    index = dist_dir / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503, detail="React frontend build is unavailable"
        )
    return FileResponse(index, media_type="text/html", headers=INDEX_CACHE_HEADERS)


def react_asset(dist_dir: Path, asset_path: str) -> FileResponse:
    asset_root = (dist_dir / "assets").resolve()
    candidate = (asset_root / asset_path).resolve()
    if candidate == asset_root or asset_root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="React asset not found")
    media_type, _ = mimetypes.guess_type(candidate.name)
    return FileResponse(
        candidate,
        media_type=media_type or "application/octet-stream",
        headers=ASSET_CACHE_HEADERS,
    )
