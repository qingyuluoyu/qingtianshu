from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class LegacySessionClaim(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)


class WatchlistUpsert(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    name: str | None = Field(default=None, max_length=80)
    market: str | None = Field(default=None, max_length=40)
    thesis: str | None = Field(default=None, max_length=1000)


class MemoryCandidateCreate(BaseModel):
    kind: str = Field(default="preference", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=2000)


class ChangeRelevanceUpdate(BaseModel):
    relevance_status: Literal["relevant", "irrelevant"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=24)
    model_tier: Literal["economy", "deep", "vision"] = "economy"
    execute_agent: bool = True
    prefer_precomputed: bool = False
    image_id: str | None = Field(default=None, max_length=36)
    conversation_id: str | None = Field(default=None, max_length=36)
    request_id: str | None = Field(default=None, min_length=8, max_length=64)
    quality_scope: Literal["user", "evaluation"] = "user"


class ChatRefineRequest(BaseModel):
    preview_run_id: str = Field(min_length=36, max_length=36)
    conversation_id: str = Field(min_length=36, max_length=36)
    assistant_message_id: str = Field(min_length=36, max_length=36)
    model_tier: Literal["economy", "deep"] = "economy"


class ConversationCreate(BaseModel):
    title: str = Field(default="新的研究对话", min_length=1, max_length=160)
    quality_scope: Literal["user", "evaluation"] = "user"


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    quality_scope: Literal["user", "evaluation"] | None = None


class DeepStockEntryContext(BaseModel):
    source_kind: Literal["stock_screen", "li_zong_strategy"]
    source_label: str = Field(min_length=1, max_length=80)
    display_name: str | None = Field(default=None, max_length=80)
    profile_key: str | None = Field(default=None, max_length=60)
    as_of_date: str | None = Field(default=None, max_length=32)
    candidate_status: str | None = Field(default=None, max_length=40)
    matched_reasons: list[str] = Field(default_factory=list, max_length=12)
    missing_fields: list[str] = Field(default_factory=list, max_length=8)


class DeepStockStart(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    conversation_id: str | None = Field(default=None, max_length=36)
    entry_context: DeepStockEntryContext | None = None


class StockRelationUpdate(BaseModel):
    base_version: int = Field(ge=1)
    relation_type: Literal["watching", "holding", "ended"]
    priority: Literal["high", "normal", "low"] | None = None
    tracking_status: Literal["active", "paused"] = "active"
    workflow_status: Literal["idle", "researching", "waiting_data"] = "idle"
    attention_tags: list[str] = Field(default_factory=list, max_length=12)


class ThesisCandidateCreate(BaseModel):
    reason_text: str = Field(min_length=1, max_length=1200)
    watch_items: list[str] = Field(default_factory=list, max_length=20)
    recheck_conditions: list[str] = Field(default_factory=list, max_length=20)
    source: Literal["user", "ai"] = "user"
    source_run_id: str | None = Field(default=None, max_length=36)
    base_version: int = Field(default=0, ge=0)


class ObservationTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    priority: Literal["high", "normal", "low"] = "normal"
    due_at: str | None = Field(default=None, max_length=40)
    thesis_id: str | None = Field(default=None, max_length=36)
    change_ref: str | None = Field(default=None, max_length=160)
    source_type: Literal["user", "research_action"] = "user"
    source_ref_id: str | None = Field(default=None, max_length=160)


class ObservationTaskUpdate(BaseModel):
    base_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: Literal["high", "normal", "low"] | None = None
    due_at: str | None = Field(default=None, max_length=40)


class ObservationTaskTransition(BaseModel):
    base_version: int = Field(ge=1)
    status: Literal[
        "pending",
        "in_progress",
        "waiting_data",
        "completed",
        "ignored",
        "cancelled",
    ]
    result_text: str | None = Field(default=None, max_length=3000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)


class PositionOpeningCreate(BaseModel):
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity: str = Field(min_length=1, max_length=40)
    cost_price: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class PositionOperationCreate(BaseModel):
    operation_type: Literal["buy", "add", "reduce", "sell"]
    operated_at: str = Field(min_length=20, max_length=40)
    price: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)
    plan_id: str | None = Field(default=None, max_length=80)


class PositionOperationRevisionCreate(BaseModel):
    base_revision: int = Field(default=0, ge=0)
    price: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=40)
    fees: str | None = Field(default=None, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)


class PositionAdjustmentCreate(BaseModel):
    adjustment_type: Literal[
        "quantity_correction", "cost_correction", "corporate_action", "other"
    ]
    effective_at: str = Field(min_length=20, max_length=40)
    quantity_delta: str = Field(default="0", min_length=1, max_length=40)
    cost_delta: str = Field(default="0", min_length=1, max_length=40)
    reason_text: str = Field(min_length=1, max_length=1200)
    evidence_text: str | None = Field(default=None, max_length=1200)


class ActionPlanCreate(BaseModel):
    action_type: Literal["buy", "add", "reduce", "sell", "hold"]
    trigger_text: str = Field(min_length=1, max_length=2000)
    target_quantity: str | None = Field(default=None, max_length=40)
    target_amount: str | None = Field(default=None, max_length=40)
    target_position_percent: str | None = Field(default=None, max_length=40)
    thesis_version_id: str | None = Field(default=None, max_length=36)
    expires_at: str | None = Field(default=None, max_length=40)


class ActionPlanPatch(BaseModel):
    base_version: int = Field(ge=1)
    action_type: Literal["buy", "add", "reduce", "sell", "hold"] | None = None
    trigger_text: str | None = Field(default=None, min_length=1, max_length=2000)
    target_quantity: str | None = Field(default=None, max_length=40)
    target_amount: str | None = Field(default=None, max_length=40)
    target_position_percent: str | None = Field(default=None, max_length=40)
    expires_at: str | None = Field(default=None, max_length=40)


class ActionPlanTransition(BaseModel):
    base_version: int = Field(ge=1)
    status: Literal["checked", "saved", "cancelled", "expired"]


class TradeReviewGenerateDraft(BaseModel):
    base_version: int = Field(default=0, ge=0)
    model_tier: Literal["economy", "deep"] = "economy"


class TradeReviewDraftPatch(BaseModel):
    base_version: int = Field(ge=1)
    price_result: str = Field(min_length=1, max_length=4000)
    logic_result: str = Field(min_length=1, max_length=6000)
    plan_deviation: str | None = Field(default=None, max_length=4000)
    bias_tags: list[str] = Field(default_factory=list, max_length=12)
    improvement_text: str | None = Field(default=None, max_length=4000)


class TradeReviewConfirm(BaseModel):
    base_version: int = Field(ge=1)


class TradeReviewFollowupCreate(BaseModel):
    target: Literal["observation_task", "thesis_draft"]
    title: str | None = Field(default=None, max_length=160)
    priority: Literal["high", "normal", "low"] = "normal"


class StockScreenFilters(BaseModel):
    min_market_cap_yi: float | None = Field(default=None, ge=0)
    max_market_cap_yi: float | None = Field(default=None, ge=0)
    min_pe_ttm: float | None = None
    max_pe_ttm: float | None = None
    min_pb: float | None = None
    max_pb: float | None = None
    min_turnover_rate: float | None = Field(default=None, ge=0)
    max_turnover_rate: float | None = Field(default=None, ge=0)
    min_volume_ratio: float | None = Field(default=None, ge=0)
    min_return_5d: float | None = None
    min_return_20d: float | None = None
    max_return_20d: float | None = None
    min_industry_excess_20d: float | None = None
    min_revenue_yoy: float | None = None
    min_net_profit_yoy: float | None = None
    min_roe: float | None = None
    industry: str | None = Field(default=None, max_length=40)
    exclude_st: bool | None = None
    min_listed_days: int | None = Field(default=None, ge=0, le=10000)


class StockScreenRequest(BaseModel):
    profile: Literal["quality", "trend", "value", "pullback"] = "trend"
    market: Literal["all", "sh", "sz", "bj", "main", "gem", "star"] = "all"
    max_results: int = Field(default=12, ge=1, le=30)
    filters: StockScreenFilters | None = None
    force_refresh: bool = False


class TushareSymbolRefreshRequest(BaseModel):
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")


class LiZongRunRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")
    refresh_data: bool = True
    roe_min_pct: float | None = Field(default=None, ge=0, le=100)


class LiZongUniverseRunRequest(BaseModel):
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")
    batch_size: int | None = Field(default=None, ge=1, le=200)


class LiZongHistoryRunRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, max_length=20)
    batch_size: int = Field(default=5, ge=1, le=20)
    lookback_days: int = Field(default=80, ge=20, le=160)


class LiZongBacktestRunRequest(BaseModel):
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-?\d{2}-?\d{2}$")
    market_day_batch_size: int = Field(default=30, ge=1, le=30)
    symbol_batch_size: int = Field(default=100, ge=1, le=200)
    input_sync_batch_size: int = Field(default=12, ge=0, le=12)


class ArticleGenerateRequest(BaseModel):
    model_tier: Literal["economy", "deep"] = "economy"
    execute_agent: bool = False


class BackgroundJobEnqueueRequest(BaseModel):
    job_name: str = Field(min_length=3, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
