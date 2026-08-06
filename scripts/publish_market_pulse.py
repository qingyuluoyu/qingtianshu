from __future__ import annotations

import json
import os

from app.main import app


def main() -> None:
    execute_agent = os.getenv("PUBLISH_WITH_HERMES", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    result = app.state.articles.generate(
        model_tier=os.getenv("PUBLISH_MODEL_TIER", "economy"),
        execute_agent=execute_agent,
        force=False,
    )
    compact = {
        "decision": result["decision"],
        "reason": result["reason"],
        "quality": result.get("quality"),
        "article_id": (result.get("article") or {}).get("id"),
        "title": (result.get("article") or {}).get("title"),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
