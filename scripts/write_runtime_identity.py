from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.runtime_identity import build_runtime_identity, write_runtime_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a non-secret identity manifest for one candidate runtime."
    )
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--database-schema", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    identity = build_runtime_identity(
        worktree=PROJECT_ROOT,
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        database_schema=args.database_schema,
    )
    print(write_runtime_identity(identity, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
