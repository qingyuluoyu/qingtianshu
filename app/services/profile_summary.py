from __future__ import annotations

from typing import Any


class ProfileSummaryService:
    """Return only user-owned, non-sensitive profile aggregates."""

    def __init__(self, database: Any) -> None:
        self._database = database

    def get(self, user_id: str) -> dict[str, Any]:
        return {
            "research_assets": {
                "watchlist_count": len(self._database.list_watchlist(user_id)),
                "conversation_count": len(
                    self._database.list_conversations(
                        user_id, include_archived=True, limit=10_000
                    )
                ),
                "run_count": len(self._database.list_user_runs(user_id, limit=10_000)),
            },
            "workbench": self._database.get_profile_workbench_snapshot(user_id),
            "membership": {
                "status": "not_available",
                "message": "会员与支付功能暂未开放。",
            },
            "data_status": "available",
        }
