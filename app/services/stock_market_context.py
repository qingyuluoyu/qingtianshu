from __future__ import annotations

from typing import Any

from app.catalog import RESEARCH_TARGETS
from app.services.chat_routing import (
    _market_date,
    _question_market_date,
    _question_price_direction,
)
from app.services.live_market import previous_market_session_date


def _stock_analysis_target(message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    current_quote = evidence.get("current_quote") or {}
    metrics = evidence.get("metrics") or {}
    history_market_date = _market_date(
        (evidence.get("provenance") or {}).get("market_timestamp")
    )
    current_quote_date = _market_date(current_quote.get("market_timestamp"))
    question_direction = _question_price_direction(message)
    quote_change = current_quote.get("pct_change")
    history_change = metrics.get("return_1d_pct")
    quote_direction = (
        1
        if isinstance(quote_change, (int, float)) and quote_change > 0
        else -1
        if isinstance(quote_change, (int, float)) and quote_change < 0
        else 0
    )
    history_direction = (
        1
        if isinstance(history_change, (int, float)) and history_change > 0
        else -1
        if isinstance(history_change, (int, float)) and history_change < 0
        else 0
    )
    explicit_market_date = _question_market_date(
        message, current_quote_date or history_market_date
    )
    if explicit_market_date:
        return {
            "market_date": explicit_market_date,
            "basis": "explicit_question_date",
            "question_direction": question_direction,
            "current_quote_market_date": current_quote_date,
            "history_market_date": history_market_date,
        }
    target_market_date = current_quote_date or history_market_date
    target_basis = "current_quote"
    if (
        question_direction
        and quote_direction
        and question_direction != quote_direction
        and question_direction == history_direction
        and history_market_date
    ):
        target_market_date = history_market_date
        target_basis = "last_complete_daily_bar"
    return {
        "market_date": target_market_date,
        "basis": target_basis,
        "question_direction": question_direction,
        "current_quote_market_date": current_quote_date,
        "history_market_date": history_market_date,
    }


def _build_stock_market_context(
    message: str,
    evidence: dict[str, Any],
    market_brief: dict[str, Any],
    industry_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    industry_snapshot = industry_snapshot or {}
    company_industry = str(
        (evidence.get("analyst_expectations") or {}).get("industry")
        or ((evidence.get("li_zong_strategy") or {}).get("stock_basic") or {}).get(
            "industry"
        )
        or (RESEARCH_TARGETS.get(str(evidence.get("symbol") or "")) or {}).get(
            "industry"
        )
        or industry_snapshot.get("industry_name")
        or ""
    ).strip()
    current_quote = evidence.get("current_quote") or {}
    metrics = evidence.get("metrics") or {}
    target = _stock_analysis_target(message, evidence)
    target_market_date = target["market_date"]
    target_basis = target["basis"]
    quote_change = current_quote.get("pct_change")
    history_change = metrics.get("return_1d_pct")
    stock_recent_bars = list(evidence.get("recent_bars") or [])
    stock_target_index = next(
        (
            index
            for index, bar in enumerate(stock_recent_bars)
            if _market_date(bar.get("timestamp")) == target_market_date
        ),
        None,
    )
    stock_target_bar = (
        stock_recent_bars[stock_target_index]
        if stock_target_index is not None
        else None
    )
    intraday_quote_target = bool(
        target_basis == "current_quote"
        and current_quote
        and stock_target_bar is None
        and target_market_date
        and target_market_date != target.get("history_market_date")
    )
    quote_basis = str(current_quote.get("quote_basis") or "")
    quote_is_post_close = quote_basis == "post_close_snapshot"
    incomplete_daily_boundary = (
        "市场已经收盘，收盘后最新报价已取得，但当天完整日线尚未入库；"
        if quote_is_post_close
        else "当前只有个股盘中最新报价，当天完整日线尚未形成；"
    )
    stock_target_return_from_bars = None
    stock_previous_bar = None
    expected_previous_market_date = previous_market_session_date(
        "china", target_market_date
    )
    if stock_target_index is not None and stock_target_index > 0:
        stock_previous_bar = stock_recent_bars[stock_target_index - 1]
        stock_previous_close = stock_previous_bar.get("close")
        stock_current_close = (
            stock_target_bar.get("close") if stock_target_bar else None
        )
        stock_previous_date = _market_date(stock_previous_bar.get("timestamp"))
        if (
            stock_previous_date == expected_previous_market_date
            and isinstance(stock_previous_close, (int, float))
            and isinstance(stock_current_close, (int, float))
            and stock_previous_close
        ):
            stock_target_return_from_bars = round(
                (float(stock_current_close) / float(stock_previous_close) - 1) * 100,
                4,
            )

    hot_sectors = market_brief.get("hot_sectors") or {}
    sectors = list(hot_sectors.get("sectors") or [])[:10]
    sector_market_date = _market_date(hot_sectors.get("market_timestamp"))
    exact_industry_matches = [
        item
        for item in sectors
        if company_industry and str(item.get("name") or "").strip() == company_industry
    ]
    industry_point = next(
        (
            point
            for point in (industry_snapshot.get("points") or [])
            if str(point.get("market_date") or "") == target_market_date
        ),
        None,
    )
    official_industry_match = bool(
        not intraday_quote_target
        and company_industry
        and industry_snapshot.get("status") == "available"
        and str(industry_snapshot.get("industry_name") or "").strip()
        == company_industry
        and industry_point
    )
    subject_constituent = next(
        (
            item
            for item in (industry_snapshot.get("constituents") or [])
            if item.get("symbol") == evidence.get("symbol")
        ),
        None,
    )
    stock_target_return = (
        stock_target_return_from_bars
        if stock_target_return_from_bars is not None
        else quote_change
        if target_basis == "current_quote"
        else None
        if stock_target_bar is not None
        else history_change
    )
    industry_return = (
        None
        if intraday_quote_target
        else industry_point.get("pct_change")
        if industry_point
        else None
    )
    stock_minus_industry = None
    if isinstance(stock_target_return, (int, float)) and isinstance(
        industry_return, (int, float)
    ):
        stock_minus_industry = round(
            float(stock_target_return) - float(industry_return), 4
        )
    component_analysis = industry_snapshot.get("component_analysis") or {}
    component_same_date = bool(
        target_market_date
        and component_analysis.get("market_date") == target_market_date
    )
    component_breadth = (
        {}
        if intraday_quote_target
        else dict(component_analysis.get("breadth") or {})
        if component_same_date
        else {}
    )
    if intraday_quote_target:
        component_breadth = {
            "status": "intraday_not_supported",
            "market_date": target_market_date,
            "boundary": (
                incomplete_daily_boundary + "行业成分的同日完整日线尚未形成；"
                "不能用少量先返回的日线样本判断行业普涨、普跌或参与面。"
            ),
        }
    elif not component_breadth:
        component_breadth = {
            "status": "unavailable_for_target_date",
            "market_date": target_market_date,
            "boundary": (
                "已取得官方样本名单，但尚未取得目标交易日全部成分股涨跌家数。"
            ),
        }
    elif component_same_date:
        component_breadth["coverage"] = dict(component_analysis.get("coverage") or {})
        component_breadth["failures"] = list(component_analysis.get("failures") or [])
        component_breadth["source_fallbacks"] = [
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "public_source_label": "新浪公开日线",
                "adjustment": item.get("adjustment"),
                "fallback_reason": item.get("fallback_reason"),
            }
            for item in (component_analysis.get("components") or [])
            if item.get("adjustment") == "unadjusted"
        ]
        component_breadth["boundary"] = component_analysis.get("boundary")
    for ratio_key in ("advance_ratio", "decline_ratio"):
        ratio_value = component_breadth.get(ratio_key)
        if isinstance(ratio_value, (int, float)):
            component_breadth[f"{ratio_key}_pct"] = round(float(ratio_value) * 100, 2)
    component_contribution = (
        {
            "status": "intraday_not_supported",
            "market_date": target_market_date,
            "boundary": (
                f"{current_quote.get('quote_label') or '最新报价'}不能与尚未形成的行业完整日线"
                "做静态成分贡献归因。"
            ),
        }
        if intraday_quote_target
        else dict(component_analysis.get("contribution") or {})
        if component_same_date
        else {}
    )
    component_rows = (
        list(component_analysis.get("components") or [])
        if component_same_date and not intraday_quote_target
        else []
    )
    subject_component = next(
        (
            item
            for item in component_rows
            if item.get("symbol") == evidence.get("symbol")
        ),
        None,
    )
    indices = []
    for item in market_brief.get("indices") or []:
        recent_bars = list(item.get("recent_bars") or [])
        matching_index = next(
            (
                index
                for index, bar in enumerate(recent_bars)
                if _market_date(bar.get("timestamp")) == target_market_date
            ),
            None,
        )
        comparison_bar = (
            recent_bars[matching_index] if matching_index is not None else None
        )
        comparison_return = None
        comparison_has_adjacent_session = False
        if matching_index is not None and matching_index > 0:
            previous_close = recent_bars[matching_index - 1].get("close")
            previous_market_date = _market_date(
                recent_bars[matching_index - 1].get("timestamp")
            )
            current_close = comparison_bar.get("close") if comparison_bar else None
            comparison_has_adjacent_session = (
                previous_market_date == expected_previous_market_date
            )
            if (
                comparison_has_adjacent_session
                and isinstance(previous_close, (int, float))
                and isinstance(current_close, (int, float))
                and previous_close
            ):
                comparison_return = round(
                    (float(current_close) / float(previous_close) - 1) * 100,
                    4,
                )
        stock_minus_index = None
        if isinstance(stock_target_return, (int, float)) and isinstance(
            comparison_return, (int, float)
        ):
            stock_minus_index = round(
                float(stock_target_return) - float(comparison_return), 4
            )
        indices.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "status": item.get("status"),
                "comparison_status": (
                    "same_market_date"
                    if comparison_bar and comparison_has_adjacent_session
                    else "missing_previous_session"
                    if comparison_bar
                    else "unavailable_for_target_date"
                ),
                "market_date": target_market_date if comparison_bar else None,
                "close": comparison_bar.get("close") if comparison_bar else None,
                "return_1d_pct": comparison_return,
                "stock_minus_index_pct": stock_minus_index,
            }
        )
    available_index_returns = [
        item["return_1d_pct"]
        for item in indices
        if isinstance(item.get("return_1d_pct"), (int, float))
    ]
    index_advancers = sum(value > 0 for value in available_index_returns)
    index_decliners = sum(value < 0 for value in available_index_returns)
    breadth_packet = market_brief.get("market_breadth") or {}
    breadth_market_date = str(breadth_packet.get("market_date") or "") or None
    breadth_same_date = bool(
        target_market_date
        and breadth_market_date
        and target_market_date == breadth_market_date
    )
    return {
        "type": "stock_market_context",
        "generated_at": market_brief.get("generated_at"),
        "market_key": "china",
        "analysis_target": {
            **target,
        },
        "stock_target": {
            "status": (
                "same_market_date"
                if stock_target_bar is not None
                else "current_quote"
                if target_basis == "current_quote" and current_quote
                else "unavailable_for_target_date"
            ),
            "market_date": target_market_date,
            "previous_market_date": (
                _market_date(stock_previous_bar.get("timestamp"))
                if stock_previous_bar
                else None
            ),
            "previous_close": (
                stock_previous_bar.get("close") if stock_previous_bar else None
            ),
            "close": (
                stock_target_bar.get("close")
                if stock_target_bar is not None
                else current_quote.get("price")
                if target_basis == "current_quote"
                else metrics.get("latest_close")
            ),
            "return_1d_pct": stock_target_return,
            "price_label": (
                current_quote.get("quote_label") or "盘中/最新报价快照"
                if intraday_quote_target
                else "完整日线收盘"
            ),
            "is_complete_daily_close": stock_target_bar is not None,
            "quote_timestamp": (
                current_quote.get("market_timestamp") if intraday_quote_target else None
            ),
            "source": (
                (evidence.get("provenance") or {}).get("source")
                if stock_target_bar is not None
                else current_quote.get("source")
            ),
        },
        "company_industry": company_industry or None,
        "exact_industry_match_available": official_industry_match
        or (bool(exact_industry_matches) and sector_market_date == target_market_date),
        "exact_industry_matches": exact_industry_matches,
        "exact_industry_index": {
            "status": (
                "intraday_not_supported"
                if intraday_quote_target
                else "same_market_date"
                if official_industry_match
                else "unavailable_for_target_date"
            ),
            "index_code": industry_snapshot.get("index_code"),
            "name": industry_snapshot.get("index_name"),
            "full_name": industry_snapshot.get("index_full_name"),
            "description": industry_snapshot.get("index_description"),
            "market_date": target_market_date if official_industry_match else None,
            "close": industry_point.get("close") if industry_point else None,
            "return_1d_pct": industry_return,
            "stock_return_1d_pct": stock_target_return,
            "stock_minus_industry_pct": stock_minus_industry,
            "constituent_count": (industry_snapshot.get("coverage") or {}).get(
                "constituents"
            ),
            "constituents_as_of": industry_snapshot.get("constituents_as_of"),
            "weights_as_of": industry_snapshot.get("weights_as_of"),
            "subject_is_constituent": subject_constituent is not None,
            "subject_weight_pct": (
                subject_constituent.get("weight_pct") if subject_constituent else None
            ),
            "industry_mapping": industry_snapshot.get("industry_mapping") or {},
            "component_breadth": component_breadth,
            "component_contribution": {
                **component_contribution,
                "subject": subject_component,
            },
            "source_url": industry_snapshot.get("source_url"),
            "constituent_source_url": industry_snapshot.get("constituent_source_url"),
        },
        "market_state": {
            "market_date": target_market_date,
            "available_indices": len(available_index_returns),
            "advancing_indices": index_advancers,
            "declining_indices": index_decliners,
            "summary": (
                f"同日可比的 {len(available_index_returns)} 个代表性指数中，"
                f"{index_advancers} 个上涨、{index_decliners} 个下跌。"
                if available_index_returns
                else "目标交易日的代表性指数对照仍待补证。"
            ),
        },
        "indices": indices,
        "hot_sectors": {
            "source": hot_sectors.get("source"),
            "market_timestamp": hot_sectors.get("market_timestamp"),
            "market_date": sector_market_date,
            "same_date_as_target": sector_market_date == target_market_date,
            "fetched_at": hot_sectors.get("fetched_at"),
            "status": hot_sectors.get("status"),
            "coverage": hot_sectors.get("coverage") or {},
            "sectors": sectors,
        },
        "market_breadth": {
            "status": breadth_packet.get("status"),
            "market_date": breadth_packet.get("market_date"),
            "same_date_as_target": breadth_same_date,
            "latest_tick_time": breadth_packet.get("latest_tick_time"),
            "coverage": breadth_packet.get("coverage") or {},
            "breadth": breadth_packet.get("breadth") or {},
            "turnover": breadth_packet.get("turnover") or {},
            "distribution": breadth_packet.get("distribution") or {},
        },
        "boundary": (
            "只能使用与 analysis_target.market_date 相同日期的代表性指数、全市场广度和板块"
            "快照判断系统性或行业拖累；跨日期证据只能说明另一个交易日的市场环境，不能拿来"
            "解释目标日涨跌。只有板块名称与公司行业精确匹配且日期一致时，才可把热门板块榜"
            "称为该公司的行业证据。经明确映射取得的中证指数必须同时展示分类映射口径；"
            "成分广度覆盖完整时才可描述行业普涨、普跌或参与面。成分贡献度是按官方权重快照"
            "与目标日复权涨跌幅做的静态估算，不是中证官方逐日归因。没有精确匹配时必须说明"
            "行业指数与成分口径仍待补证。"
        ),
    }
