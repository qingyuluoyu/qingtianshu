from __future__ import annotations

import argparse
import os
from pathlib import Path
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qingshu-start",
        description="启动清数智算金融研究工作台。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="显式指定 .env 文件；默认依次读取当前目录和源码目录的 .env",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动后不自动打开产品页面",
    )
    return parser


def _browser_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _open_product_when_ready(host: str, port: int) -> None:
    base_url = f"http://{_browser_host(host)}:{port}"
    for _ in range(80):
        try:
            with urlopen(f"{base_url}/health", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(f"{base_url}/today")
                    return
        except (OSError, URLError):
            time.sleep(0.25)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在 1—65535 之间")
    if args.env_file is not None:
        os.environ["QINGSHU_ENV_FILE"] = str(args.env_file.expanduser().resolve())
    if not args.no_browser:
        threading.Thread(
            target=_open_product_when_ready,
            args=(args.host, args.port),
            daemon=True,
        ).start()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        timeout_graceful_shutdown=3,
    )
