from __future__ import annotations

import argparse
import signal

from app.main import app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qingshu-worker",
        description="运行清数智算持久化后台任务 Worker。",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="最多执行一个到期任务后退出，适合部署探针和手工验证。",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    background = app.state.background

    def stop_worker(*_: object) -> None:
        background.stop()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    if args.once:
        background.run_once()
        return
    background.run_forever()


if __name__ == "__main__":
    main()
