from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
import threading
import time
from typing import Any, Iterable

import pandas as pd

from app.catalog import normalize_symbol
from app.utils import utc_now


_FINA_FIELDS = (
    "ts_code,ann_date,end_date,update_flag,profit_dedt,q_sales_yoy,"
    "q_dtprofit_yoy,roe,roic,current_ratio,quick_ratio,debt_to_assets,"
    "assets_turn,ebit,tr_yoy,netprofit_yoy"
)
_INCOME_FIELDS = (
    "ts_code,ann_date,end_date,report_type,update_flag,revenue,oper_cost,"
    "operate_profit,total_profit,income_tax,n_income_attr_p,fin_exp_int_exp"
)
_BALANCE_FIELDS = (
    "ts_code,ann_date,end_date,report_type,update_flag,money_cap,"
    "accounts_receiv,inventories,total_cur_assets,total_assets,st_borr,"
    "st_bonds_payable,non_cur_liab_due_1y,total_cur_liab,bond_payable,"
    "lt_borr,lease_liab,total_liab,total_hldr_eqy_exc_min_int"
)
_CASHFLOW_FIELDS = (
    "ts_code,ann_date,end_date,report_type,update_flag,c_fr_sale_sg,"
    "n_cashflow_act,c_pay_acq_const_fiolta"
)
_DAILY_BASIC_FIELDS = "ts_code,trade_date,pe_ttm,pb,ps_ttm,total_mv"
_MEMBER_FIELDS = (
    "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,"
    "in_date,out_date,is_new"
)

_FULL_SAMPLE_SIZE = 20
_MIN_SAMPLE_SIZE = 10
_MIN_HISTORY_DAYS = 504
_HISTORY_DAYS = 1260
_MIN_OPERATING_CASH_REVENUE_RATIO = 0.05
_CASH_SHORT_DEBT_RANKING_CAP = 10.0


class IndustryComparisonService:
    """Five-factor, point-in-time SW2 comparison for the stock score page."""

    METHOD = "sw2_five_factor_comparison_v1"
    FORMULA_VERSION = "financial_factor_v1.0"

    def __init__(
        self,
        tushare_client: Any | None,
        *,
        database: Any | None = None,
        cache_seconds: int = 3_600,
        batch_cache_seconds: int = 21_600,
        stale_seconds: int = 604_800,
        background_refresh: bool = False,
    ) -> None:
        self.client = tushare_client
        self.database = database
        self.cache_seconds = max(300, int(cache_seconds))
        self.batch_cache_seconds = max(self.cache_seconds, int(batch_cache_seconds))
        self.stale_seconds = max(self.cache_seconds, int(stale_seconds))
        self.background_refresh = background_refresh
        self._lock = threading.RLock()
        self._build_lock = threading.Lock()
        self._packet_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._frame_cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._refreshing: set[str] = set()
        self._executor = (
            ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="qingshu-industry-refresh",
            )
            if background_refresh
            else None
        )

    def get_packet(self, symbol: str, *, force: bool = False) -> dict[str, Any]:
        canonical = _canonical_a_share(symbol)
        now = time.monotonic()
        if not force:
            with self._lock:
                cached = self._packet_cache.get(canonical)
                if cached and cached[0] > now:
                    return self._with_cache_state(
                        cached[1],
                        state="fresh",
                    )

            persistent = self._persistent_cache(canonical)
            if persistent is not None and self._packet_is_fresh(persistent):
                with self._lock:
                    self._packet_cache[canonical] = (
                        time.monotonic() + self.cache_seconds,
                        persistent,
                    )
                return self._with_cache_state(
                    persistent,
                    state="fresh",
                )

        stale = persistent if not force else None
        if stale is None:
            stale = self._persistent_cache(
                canonical,
                allow_stale=True,
            )
        if stale is not None and self._stale_is_usable(stale):
            if self.background_refresh:
                self._schedule_refresh(canonical)
                return self._with_cache_state(
                    stale,
                    state="stale",
                    refreshing=True,
                )
            if not force:
                return self._with_cache_state(stale, state="stale")

        if self.background_refresh:
            self._schedule_refresh(canonical)
            return self._warming_packet(canonical)

        return self._refresh_packet(canonical)

    def prewarm(self, symbols: Iterable[str]) -> None:
        if not self.background_refresh:
            return
        for symbol in dict.fromkeys(symbols):
            try:
                canonical = _canonical_a_share(symbol)
            except ValueError:
                continue
            if self._persistent_cache(canonical) is None:
                self._schedule_refresh(canonical)

    def refresh_packet(self, symbol: str) -> dict[str, Any]:
        """Refresh one public comparison snapshot from the Worker."""
        return self._refresh_packet(_canonical_a_share(symbol))

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _refresh_packet(self, canonical: str) -> dict[str, Any]:
        if self.client is None:
            raise ValueError("Tushare 数据接口尚未配置")
        with self._build_lock:
            packet = self._build_packet(canonical)
            with self._lock:
                self._packet_cache[canonical] = (
                    time.monotonic() + self.cache_seconds,
                    packet,
                )
            if self.database is not None:
                self.database.put_cache(
                    self._cache_key(canonical),
                    packet,
                    self.stale_seconds,
                )
            return self._with_cache_state(packet, state="refreshed")

    def _schedule_refresh(self, canonical: str) -> None:
        if self._executor is None:
            return
        with self._lock:
            if canonical in self._refreshing:
                return
            self._refreshing.add(canonical)
        self._executor.submit(self._refresh_job, canonical)

    def _refresh_job(self, canonical: str) -> None:
        try:
            self._refresh_packet(canonical)
        except Exception:
            pass
        finally:
            with self._lock:
                self._refreshing.discard(canonical)

    def _persistent_cache(
        self,
        canonical: str,
        *,
        allow_stale: bool = False,
    ) -> dict[str, Any] | None:
        if self.database is None:
            return None
        return self.database.get_cache(
            self._cache_key(canonical),
            allow_stale=allow_stale,
        )

    def _cache_key(self, canonical: str) -> str:
        return f"industry-comparison:{self.METHOD}:{canonical}"

    def _stale_is_usable(self, packet: dict[str, Any]) -> bool:
        age = self._packet_age_seconds(packet)
        return age is not None and age <= self.stale_seconds

    def _packet_is_fresh(self, packet: dict[str, Any]) -> bool:
        age = self._packet_age_seconds(packet)
        return age is not None and age <= self.cache_seconds

    @staticmethod
    def _packet_age_seconds(packet: dict[str, Any]) -> float | None:
        generated_at = packet.get("generatedAt") or packet.get("fetched_at")
        if not generated_at:
            return None
        try:
            generated = datetime.fromisoformat(
                str(generated_at).replace("Z", "+00:00")
            )
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - generated.astimezone(timezone.utc)
            return max(0.0, age.total_seconds())
        except (TypeError, ValueError):
            return None

    def _with_cache_state(
        self,
        packet: dict[str, Any],
        *,
        state: str,
        refreshing: bool = False,
    ) -> dict[str, Any]:
        result = _deep_copy(packet)
        result["cache"] = {
            "state": state,
            "refreshing": refreshing,
        }
        return result

    def _warming_packet(self, canonical: str) -> dict[str, Any]:
        return {
            "symbol": _to_tushare_symbol(canonical),
            "internalSymbol": canonical,
            "name": canonical,
            "status": "warming",
            "industry": {},
            "reportPeriod": None,
            "valuationTradeDate": None,
            "generatedAt": utc_now(),
            "coverage": {
                "industryMembers": 0,
                "financialMembersAtAnchor": 0,
                "valuationMembers": 0,
                "availableFactors": 0,
                "totalFactors": 5,
            },
            "radar": {
                "labels": [],
                "subject": [],
                "industryMedian": [],
            },
            "topMetricComparison": {"series": []},
            "factors": [],
            "warnings": ["行业对比数据正在后台准备，请稍后刷新。"],
            "sources": [],
            "cache": {
                "state": "warming",
                "refreshing": True,
            },
        }

    def _build_packet(self, canonical: str) -> dict[str, Any]:
        subject_code = _to_tushare_symbol(canonical)
        warnings: list[str] = []
        member_frame = self._query_frame(
            "index_member_all",
            ts_code=subject_code,
            fields=_MEMBER_FIELDS,
        )
        subject_memberships = _records(member_frame)
        current_membership = next(
            (
                item
                for item in subject_memberships
                if str(item.get("is_new") or "").upper() == "Y"
                and item.get("l2_code")
            ),
            None,
        )
        if current_membership is None:
            current_membership = next(
                (item for item in subject_memberships if item.get("l2_code")),
                None,
            )
        if current_membership is None:
            raise ValueError("该股票暂无可用的申万二级行业归属")

        l2_code = str(current_membership["l2_code"])
        all_members = _records(
            self._query_frame(
                "index_member_all",
                l2_code=l2_code,
                fields=_MEMBER_FIELDS,
            )
        )
        current_members = [
            item
            for item in all_members
            if str(item.get("is_new") or "").upper() == "Y"
            or not str(item.get("out_date") or "").strip()
        ]
        current_codes = {
            str(item.get("ts_code") or "").upper()
            for item in current_members
            if _is_a_share_code(item.get("ts_code"))
            and not _is_st_name(item.get("name"))
        }
        current_codes.add(subject_code)
        anchor_period, anchor_rows = self._select_anchor_period(
            subject_code, current_codes, warnings=warnings
        )

        members = [
            item
            for item in all_members
            if _member_active_on(item, anchor_period)
            and _is_a_share_code(item.get("ts_code"))
            and not _is_st_name(item.get("name"))
        ]
        member_by_code = {
            str(item.get("ts_code") or "").upper(): item for item in members
        }
        if subject_code not in member_by_code:
            member_by_code[subject_code] = current_membership
        peer_codes = set(member_by_code)

        financial_rows = self._load_financial_rows(
            anchor_period, warnings=warnings
        )
        values_by_code = {
            code: self._financial_values(
                code,
                anchor_period=anchor_period,
                rows=financial_rows,
            )
            for code in peer_codes
        }

        valuation_date, valuation_frame = self._latest_valuation_cross_section()
        valuation_rows = _latest_rows(valuation_frame)
        valuation_by_code = {
            code: row for code, row in valuation_rows.items() if code in peer_codes
        }
        subject_history = self._valuation_history(subject_code, valuation_date)

        factors = [
            self._industry_factor(
                "growth",
                "成长性",
                [
                    ("revenue_q_yoy", "单季度营业收入同比", 30.0, "higher", "%"),
                    (
                        "deduct_q_yoy",
                        "单季度扣非净利润同比",
                        35.0,
                        "higher",
                        "%",
                    ),
                    ("revenue_cagr3", "收入3年CAGR", 15.0, "higher", "%"),
                    (
                        "revenue_growth_acceleration",
                        "收入成长加速度",
                        10.0,
                        "higher",
                        "百分点",
                    ),
                    (
                        "deduct_growth_acceleration",
                        "扣非利润成长加速度",
                        10.0,
                        "higher",
                        "百分点",
                    ),
                ],
                subject_code,
                values_by_code,
            ),
            self._valuation_factor(
                subject_code,
                valuation_by_code,
                subject_history,
            ),
            self._industry_factor(
                "profitability",
                "盈利能力",
                [
                    ("roe_ttm", "ROE TTM", 35.0, "higher", "%"),
                    ("roic_ttm", "ROIC TTM", 25.0, "higher", "%"),
                    ("gross_margin", "单季度毛利率", 20.0, "higher", "%"),
                    ("net_margin", "单季度净利率", 20.0, "higher", "%"),
                ],
                subject_code,
                values_by_code,
            ),
            self._industry_factor(
                "stability",
                "财务稳健性",
                [
                    ("debt_asset", "资产负债率", 30.0, "lower", "%"),
                    ("net_debt_ratio", "净负债率", 20.0, "lower", "%"),
                    (
                        "cash_short_debt",
                        "现金短债比",
                        20.0,
                        "higher",
                        "倍",
                    ),
                    ("current_ratio", "流动比率", 7.5, "higher", "倍"),
                    ("quick_ratio", "速动比率", 7.5, "higher", "倍"),
                    (
                        "earnings_volatility",
                        "12季度扣非利润增速波动",
                        15.0,
                        "lower",
                        "百分点",
                    ),
                ],
                subject_code,
                values_by_code,
            ),
            self._industry_factor(
                "efficiency",
                "经营效率",
                [
                    (
                        "ocf_to_net_profit",
                        "OCF/净利润 TTM",
                        30.0,
                        "higher",
                        "倍",
                    ),
                    (
                        "asset_turnover",
                        "总资产周转率",
                        20.0,
                        "higher",
                        "次",
                    ),
                    (
                        "receivable_growth_gap",
                        "应收增速差",
                        20.0,
                        "lower",
                        "百分点",
                    ),
                    (
                        "inventory_growth_gap",
                        "存货增速差",
                        15.0,
                        "lower",
                        "百分点",
                    ),
                    (
                        "cash_sales_ratio",
                        "现金收入比",
                        15.0,
                        "higher",
                        "倍",
                    ),
                ],
                subject_code,
                values_by_code,
            ),
        ]
        top_metric_comparison = {
            "industryCode": l2_code,
            "industryName": current_membership.get("l2_name"),
            "financialReportPeriod": _iso_period(anchor_period),
            "valuationTradeDate": _iso_period(valuation_date),
            "series": [
                _comparison_summary(
                    key="peTtm",
                    label="PE (TTM)",
                    unit="倍",
                    subject_code=subject_code,
                    values={
                        code: _number(row.get("pe_ttm"))
                        for code, row in valuation_by_code.items()
                    },
                    positive_only=True,
                    data_date=_iso_period(valuation_date),
                ),
                _comparison_summary(
                    key="pbLf",
                    label="PB (LF)",
                    unit="倍",
                    subject_code=subject_code,
                    values={
                        code: _number(row.get("pb"))
                        for code, row in valuation_by_code.items()
                    },
                    positive_only=True,
                    data_date=_iso_period(valuation_date),
                ),
                _comparison_summary(
                    key="roeWeightedReport",
                    label="加权ROE（报告期）",
                    unit="%",
                    subject_code=subject_code,
                    values={
                        code: payload.get("roe_report")
                        for code, payload in values_by_code.items()
                    },
                    data_date=_iso_period(anchor_period),
                ),
                _comparison_summary(
                    key="revenueYoy",
                    label="营收同比",
                    unit="%",
                    subject_code=subject_code,
                    values={
                        code: payload.get("revenue_yoy_report")
                        for code, payload in values_by_code.items()
                    },
                    data_date=_iso_period(anchor_period),
                ),
                _comparison_summary(
                    key="parentNetProfitYoy",
                    label="归母净利润同比",
                    unit="%",
                    subject_code=subject_code,
                    values={
                        code: payload.get("parent_profit_yoy_report")
                        for code, payload in values_by_code.items()
                    },
                    data_date=_iso_period(anchor_period),
                ),
            ],
        }

        is_financial = str(current_membership.get("l1_name") or "") in {
            "银行",
            "非银金融",
        }
        if is_financial:
            warnings.append(
                "银行、保险和证券公司需要专用财务模型；当前仅保留估值结果，其他维度不作为正式评分。"
            )
            factors = [
                factor
                if factor["key"] == "valuation"
                else {
                    **factor,
                    "score": None,
                    "status": "not_applicable",
                    "state": "金融行业需专用模型",
                }
                for factor in factors
            ]

        available_factor_count = sum(
            factor.get("score") is not None for factor in factors
        )
        module_status = (
            "available"
            if available_factor_count == len(factors)
            else "partial"
            if available_factor_count
            else "unavailable"
        )
        subject_member = member_by_code.get(subject_code) or current_membership
        anchor_financial_count = sum(code in anchor_rows for code in peer_codes)
        warnings.extend(
            [
                "五维分数是申万二级行业内的相对位置，不是买卖建议或绝对优劣评级。",
                "ROIC 超额现金按货币资金减去营收TTM的5%计算；受限资金无法从结构化字段中完全拆分。",
                "现金短债比为保证行业排名稳定，短债为零或极低时按10倍封顶参与排名。",
            ]
        )
        return {
            "symbol": subject_code,
            "internalSymbol": canonical,
            "name": subject_member.get("name") or subject_code,
            "status": module_status,
            "industry": {
                "standard": "申万2021",
                "level": "L2",
                "l1Code": subject_member.get("l1_code"),
                "l1Name": subject_member.get("l1_name"),
                "code": l2_code,
                "name": subject_member.get("l2_name"),
            },
            "reportPeriod": _iso_period(anchor_period),
            "valuationTradeDate": _iso_period(valuation_date),
            "generatedAt": utc_now(),
            "coverage": {
                "industryMembers": len(peer_codes),
                "financialMembersAtAnchor": anchor_financial_count,
                "valuationMembers": len(valuation_by_code),
                "availableFactors": available_factor_count,
                "totalFactors": len(factors),
            },
            "radar": {
                "labels": [factor["label"] for factor in factors],
                "subject": [factor.get("score") for factor in factors],
                "industryMedian": [50.0 for _ in factors],
            },
            "topMetricComparison": top_metric_comparison,
            "factors": factors,
            "formulaPolicy": {
                "industryStandard": "SW2021-L2",
                "minimumOperatingCashRatio": _MIN_OPERATING_CASH_REVENUE_RATIO,
                "leaseLiabilityIncluded": True,
                "notesPayableIncluded": False,
                "longTermPayableDefaultIncluded": False,
                "cashShortDebtRankingCap": _CASH_SHORT_DEBT_RANKING_CAP,
                "fullSampleSize": _FULL_SAMPLE_SIZE,
                "minimumSampleSize": _MIN_SAMPLE_SIZE,
                "historyWindowTradingDays": _HISTORY_DAYS,
                "minimumHistoryDays": _MIN_HISTORY_DAYS,
            },
            "warnings": list(dict.fromkeys(warnings)),
            "sources": [
                "Tushare index_member_all / SW2021",
                "Tushare daily_basic",
                "Tushare fina_indicator_vip",
                "Tushare income_vip",
                "Tushare balancesheet_vip",
                "Tushare cashflow_vip",
            ],
            "method": self.METHOD,
            "formulaVersion": self.FORMULA_VERSION,
        }

    def _select_anchor_period(
        self,
        subject_code: str,
        peer_codes: set[str],
        *,
        warnings: list[str],
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        target = (
            _FULL_SAMPLE_SIZE
            if len(peer_codes) >= _FULL_SAMPLE_SIZE
            else _MIN_SAMPLE_SIZE
            if len(peer_codes) >= _MIN_SAMPLE_SIZE
            else 1
        )
        fallback: tuple[str, dict[str, dict[str, Any]]] | None = None
        complete_fallback: tuple[str, dict[str, dict[str, Any]]] | None = None
        latest_financial_period: str | None = None
        for period in _recent_quarter_periods(date.today(), count=12):
            rows = self._period_rows("fina_indicator_vip", period)
            matching = {code: row for code, row in rows.items() if code in peer_codes}
            if subject_code not in matching:
                continue
            if latest_financial_period is None:
                latest_financial_period = period
            if fallback is None:
                fallback = (period, matching)
            if not self._subject_has_complete_core(subject_code, period):
                continue
            if complete_fallback is None:
                complete_fallback = (period, matching)
            if len(matching) >= target:
                if latest_financial_period != period:
                    warnings.append(
                        "最新报告期的现金流或资产负债数据不完整，五维比较已自动回退到最近一个可完整计算的报告期。"
                    )
                return period, matching
        if complete_fallback is not None:
            return complete_fallback
        if fallback is not None:
            warnings.append(
                "可用报告期仍有核心报表字段缺失，部分维度可能无法评分。"
            )
            return fallback
        raise ValueError("没有找到该股票与同行可对齐的财务报告期")

    def _subject_has_complete_core(
        self, subject_code: str, period: str
    ) -> bool:
        prior_year = _shift_quarter(period, -4)
        last_fy = _last_completed_fy(period)
        requirements = [
            ("income_vip", period, ("revenue", "n_income_attr_p")),
            (
                "balancesheet_vip",
                period,
                ("total_assets", "total_hldr_eqy_exc_min_int"),
            ),
            (
                "balancesheet_vip",
                prior_year,
                ("total_assets", "total_hldr_eqy_exc_min_int"),
            ),
            (
                "cashflow_vip",
                period,
                ("n_cashflow_act", "c_fr_sale_sg"),
            ),
        ]
        if not period.endswith("1231"):
            requirements.extend(
                [
                    (
                        "income_vip",
                        last_fy,
                        ("revenue", "n_income_attr_p"),
                    ),
                    (
                        "income_vip",
                        prior_year,
                        ("revenue", "n_income_attr_p"),
                    ),
                    (
                        "cashflow_vip",
                        last_fy,
                        ("n_cashflow_act", "c_fr_sale_sg"),
                    ),
                    (
                        "cashflow_vip",
                        prior_year,
                        ("n_cashflow_act", "c_fr_sale_sg"),
                    ),
                ]
            )
        try:
            for api_name, report_period, fields in requirements:
                row = self._period_rows(api_name, report_period).get(
                    subject_code
                )
                if not row or any(_number(row.get(field)) is None for field in fields):
                    return False
        except Exception:
            return False
        return True

    def _load_financial_rows(
        self, anchor: str, *, warnings: list[str]
    ) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        previous = _shift_quarter(anchor, -1)
        previous_previous = _shift_quarter(previous, -1)
        prior_year = _shift_quarter(anchor, -4)
        prior_year_previous = _shift_quarter(prior_year, -1)
        previous_prior_year = _shift_quarter(previous, -4)
        previous_prior_year_previous = _shift_quarter(previous_prior_year, -1)
        last_fy = _last_completed_fy(anchor)
        last_fy_3 = f"{int(last_fy[:4]) - 3}1231"
        prior_prior_year = _shift_quarter(prior_year, -4)
        prior_last_fy = _last_completed_fy(prior_year)

        periods_by_api = {
            "fina_indicator_vip": {
                anchor,
                previous,
                previous_previous,
                prior_year,
                prior_year_previous,
                previous_prior_year,
                previous_prior_year_previous,
                last_fy,
                last_fy_3,
            },
            "income_vip": {
                anchor,
                previous,
                prior_year,
                prior_year_previous,
                last_fy,
                last_fy_3,
                prior_prior_year,
                prior_last_fy,
            },
            "balancesheet_vip": {anchor, prior_year},
            "cashflow_vip": {anchor, prior_year, last_fy},
        }
        result: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for api_name, periods in periods_by_api.items():
            result[api_name] = {}
            for period in sorted(periods):
                try:
                    result[api_name][period] = self._period_rows(api_name, period)
                except Exception as exc:
                    result[api_name][period] = {}
                    warnings.append(
                        f"{api_name} {period} 暂不可用：{type(exc).__name__}"
                    )
        return result

    def _period_rows(
        self, api_name: str, period: str
    ) -> dict[str, dict[str, Any]]:
        fields = {
            "fina_indicator_vip": _FINA_FIELDS,
            "income_vip": _INCOME_FIELDS,
            "balancesheet_vip": _BALANCE_FIELDS,
            "cashflow_vip": _CASHFLOW_FIELDS,
        }[api_name]
        return _latest_rows(
            self._query_frame(api_name, period=period, fields=fields)
        )

    def _latest_valuation_cross_section(self) -> tuple[str, pd.DataFrame]:
        end = date.today()
        start = end - timedelta(days=20)
        calendar_frame = self._query_frame(
            "trade_cal",
            exchange="SSE",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            is_open="1",
            fields="cal_date,is_open",
        )
        candidates = sorted(
            {
                str(value)
                for value in calendar_frame.get("cal_date", pd.Series(dtype=str))
                if str(value)
            },
            reverse=True,
        )
        if not candidates:
            candidates = [
                (end - timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(0, 15)
            ]
        for trade_date in candidates:
            frame = self._query_frame(
                "daily_basic",
                trade_date=trade_date,
                fields=_DAILY_BASIC_FIELDS,
            )
            if not frame.empty:
                return trade_date, frame
        raise ValueError("没有找到最近完整交易日的估值截面")

    def _valuation_history(
        self, subject_code: str, valuation_date: str
    ) -> pd.DataFrame:
        end = datetime.strptime(valuation_date, "%Y%m%d").date()
        start = end - timedelta(days=365 * 6 + 10)
        frame = self._query_frame(
            "daily_basic",
            ts_code=subject_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=valuation_date,
            fields=_DAILY_BASIC_FIELDS,
        )
        if "trade_date" in frame:
            frame = frame.sort_values("trade_date")
        return frame

    def _financial_values(
        self,
        code: str,
        *,
        anchor_period: str,
        rows: dict[str, dict[str, dict[str, dict[str, Any]]]],
    ) -> dict[str, float | None]:
        previous = _shift_quarter(anchor_period, -1)
        prior_year = _shift_quarter(anchor_period, -4)
        prior_year_previous = _shift_quarter(prior_year, -1)
        last_fy = _last_completed_fy(anchor_period)
        last_fy_3 = f"{int(last_fy[:4]) - 3}1231"

        def value(api: str, period: str, field: str) -> float | None:
            return _number(
                (((rows.get(api) or {}).get(period) or {}).get(code) or {}).get(
                    field
                )
            )

        def single_quarter(api: str, period: str, field: str) -> float | None:
            current = value(api, period, field)
            if current is None:
                return None
            if period.endswith("0331"):
                return current
            preceding = value(api, _shift_quarter(period, -1), field)
            return current - preceding if preceding is not None else None

        def ttm(api: str, period: str, field: str) -> float | None:
            current = value(api, period, field)
            if current is None:
                return None
            if period.endswith("1231"):
                return current
            annual = value(api, _last_completed_fy(period), field)
            prior = value(api, _shift_quarter(period, -4), field)
            if annual is None or prior is None:
                return None
            return current + annual - prior

        def q_yoy(api: str, period: str, field: str) -> float | None:
            current = single_quarter(api, period, field)
            comparable = single_quarter(api, _shift_quarter(period, -4), field)
            return _growth_pct(current, comparable)

        subject_fina = (
            ((rows.get("fina_indicator_vip") or {}).get(anchor_period) or {}).get(
                code
            )
            or {}
        )
        roe_report = _number(subject_fina.get("roe"))
        revenue_yoy_report = _number(subject_fina.get("tr_yoy"))
        if revenue_yoy_report is None:
            revenue_yoy_report = _growth_pct(
                value("income_vip", anchor_period, "revenue"),
                value("income_vip", prior_year, "revenue"),
            )
        parent_profit_yoy_report = _number(
            subject_fina.get("netprofit_yoy")
        )
        if parent_profit_yoy_report is None:
            parent_profit_yoy_report = _growth_pct(
                value("income_vip", anchor_period, "n_income_attr_p"),
                value("income_vip", prior_year, "n_income_attr_p"),
            )
        revenue_q_yoy = _number(subject_fina.get("q_sales_yoy"))
        if revenue_q_yoy is None:
            revenue_q_yoy = q_yoy(
                "income_vip", anchor_period, "revenue"
            )
        deduct_q_yoy = _number(subject_fina.get("q_dtprofit_yoy"))
        if deduct_q_yoy is None:
            deduct_q_yoy = q_yoy(
                "fina_indicator_vip", anchor_period, "profit_dedt"
            )

        previous_fina = (
            ((rows.get("fina_indicator_vip") or {}).get(previous) or {}).get(code)
            or {}
        )
        previous_revenue_q_yoy = _number(previous_fina.get("q_sales_yoy"))
        if previous_revenue_q_yoy is None:
            previous_revenue_q_yoy = q_yoy(
                "income_vip", previous, "revenue"
            )
        previous_deduct_q_yoy = _number(previous_fina.get("q_dtprofit_yoy"))
        if previous_deduct_q_yoy is None:
            previous_deduct_q_yoy = q_yoy(
                "fina_indicator_vip", previous, "profit_dedt"
            )

        revenue_fy = value("income_vip", last_fy, "revenue")
        revenue_fy_3 = value("income_vip", last_fy_3, "revenue")
        revenue_cagr3 = (
            ((revenue_fy / revenue_fy_3) ** (1.0 / 3.0) - 1.0) * 100.0
            if revenue_fy is not None
            and revenue_fy_3 is not None
            and revenue_fy > 0
            and revenue_fy_3 > 0
            else None
        )

        revenue_q = single_quarter("income_vip", anchor_period, "revenue")
        cost_q = single_quarter("income_vip", anchor_period, "oper_cost")
        profit_q = single_quarter(
            "income_vip", anchor_period, "n_income_attr_p"
        )
        gross_margin = _ratio_pct(
            revenue_q - cost_q
            if revenue_q is not None and cost_q is not None
            else None,
            revenue_q,
        )
        net_margin = _ratio_pct(profit_q, revenue_q)

        revenue_ttm = ttm("income_vip", anchor_period, "revenue")
        profit_ttm = ttm(
            "income_vip", anchor_period, "n_income_attr_p"
        )
        operating_profit_ttm = ttm(
            "income_vip", anchor_period, "operate_profit"
        )
        interest_expense_ttm = ttm(
            "income_vip", anchor_period, "fin_exp_int_exp"
        )
        total_profit_ttm = ttm(
            "income_vip", anchor_period, "total_profit"
        )
        income_tax_ttm = ttm("income_vip", anchor_period, "income_tax")
        operating_cashflow_ttm = ttm(
            "cashflow_vip", anchor_period, "n_cashflow_act"
        )
        sales_cash_ttm = ttm(
            "cashflow_vip", anchor_period, "c_fr_sale_sg"
        )

        equity = value(
            "balancesheet_vip",
            anchor_period,
            "total_hldr_eqy_exc_min_int",
        )
        prior_equity = value(
            "balancesheet_vip",
            prior_year,
            "total_hldr_eqy_exc_min_int",
        )
        assets = value("balancesheet_vip", anchor_period, "total_assets")
        prior_assets = value("balancesheet_vip", prior_year, "total_assets")
        average_equity = _average_positive(equity, prior_equity)
        average_assets = _average_positive(assets, prior_assets)
        roe_ttm = _ratio_pct(profit_ttm, average_equity)

        debt = _interest_bearing_debt(
            lambda field: value("balancesheet_vip", anchor_period, field)
        )
        prior_debt = _interest_bearing_debt(
            lambda field: value("balancesheet_vip", prior_year, field)
        )
        short_debt = _short_interest_bearing_debt(
            lambda field: value("balancesheet_vip", anchor_period, field)
        )
        cash = value("balancesheet_vip", anchor_period, "money_cap")
        prior_cash = value("balancesheet_vip", prior_year, "money_cap")
        prior_revenue_ttm = ttm("income_vip", prior_year, "revenue")
        excess_cash = _excess_cash(cash, revenue_ttm)
        prior_excess_cash = _excess_cash(prior_cash, prior_revenue_ttm)
        invested_capital = _invested_capital(equity, debt, excess_cash)
        prior_invested_capital = _invested_capital(
            prior_equity, prior_debt, prior_excess_cash
        )
        average_invested_capital = _average_positive(
            invested_capital, prior_invested_capital
        )
        tax_rate = (
            income_tax_ttm / total_profit_ttm
            if income_tax_ttm is not None
            and total_profit_ttm is not None
            and total_profit_ttm > 0
            and income_tax_ttm >= 0
            else None
        )
        if tax_rate is not None:
            tax_rate = min(0.35, max(0.0, tax_rate))
        ebit_ttm = (
            operating_profit_ttm + interest_expense_ttm
            if operating_profit_ttm is not None
            and interest_expense_ttm is not None
            else None
        )
        if ebit_ttm is None:
            ebit_ttm = ttm(
                "fina_indicator_vip", anchor_period, "ebit"
            )
        nopat = (
            ebit_ttm * (1.0 - tax_rate)
            if ebit_ttm is not None and tax_rate is not None
            else None
        )
        roic_ttm = _ratio_pct(nopat, average_invested_capital)

        liabilities = value(
            "balancesheet_vip", anchor_period, "total_liab"
        )
        debt_asset = _number(subject_fina.get("debt_to_assets"))
        if debt_asset is None:
            debt_asset = _ratio_pct(liabilities, assets)
        net_debt_ratio = _ratio_pct(
            debt - cash
            if debt is not None and cash is not None
            else None,
            equity,
        )
        cash_short_debt = (
            _CASH_SHORT_DEBT_RANKING_CAP
            if short_debt == 0 and cash is not None
            else min(
                _CASH_SHORT_DEBT_RANKING_CAP,
                cash / short_debt,
            )
            if short_debt is not None
            and short_debt > 0
            and cash is not None
            else None
        )
        current_assets = value(
            "balancesheet_vip", anchor_period, "total_cur_assets"
        )
        current_liabilities = value(
            "balancesheet_vip", anchor_period, "total_cur_liab"
        )
        inventory = value(
            "balancesheet_vip", anchor_period, "inventories"
        )
        current_ratio = _number(subject_fina.get("current_ratio"))
        if current_ratio is None:
            current_ratio = _ratio(current_assets, current_liabilities)
        quick_ratio = _number(subject_fina.get("quick_ratio"))
        if quick_ratio is None:
            quick_ratio = _ratio(
                current_assets - inventory
                if current_assets is not None and inventory is not None
                else None,
                current_liabilities,
            )

        receivable = value(
            "balancesheet_vip", anchor_period, "accounts_receiv"
        )
        prior_receivable = value(
            "balancesheet_vip", prior_year, "accounts_receiv"
        )
        prior_inventory = value(
            "balancesheet_vip", prior_year, "inventories"
        )
        receivable_growth = _growth_pct(receivable, prior_receivable)
        inventory_growth = _growth_pct(inventory, prior_inventory)

        return {
            "roe_report": roe_report,
            "revenue_yoy_report": revenue_yoy_report,
            "parent_profit_yoy_report": parent_profit_yoy_report,
            "revenue_q_yoy": revenue_q_yoy,
            "deduct_q_yoy": deduct_q_yoy,
            "revenue_cagr3": revenue_cagr3,
            "revenue_growth_acceleration": _difference(
                revenue_q_yoy, previous_revenue_q_yoy
            ),
            "deduct_growth_acceleration": _difference(
                deduct_q_yoy, previous_deduct_q_yoy
            ),
            "roe_ttm": roe_ttm,
            "roic_ttm": roic_ttm,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "debt_asset": debt_asset,
            "net_debt_ratio": net_debt_ratio,
            "cash_short_debt": cash_short_debt,
            "current_ratio": current_ratio,
            "quick_ratio": quick_ratio,
            "earnings_volatility": None,
            "ocf_to_net_profit": _ratio(
                operating_cashflow_ttm, profit_ttm
            ),
            "asset_turnover": _ratio(revenue_ttm, average_assets),
            "receivable_growth_gap": _difference(
                receivable_growth, revenue_q_yoy
            ),
            "inventory_growth_gap": _difference(
                inventory_growth, revenue_q_yoy
            ),
            "cash_sales_ratio": _ratio(sales_cash_ttm, revenue_ttm),
        }

    def _industry_factor(
        self,
        key: str,
        label: str,
        specs: list[tuple[str, str, float, str, str]],
        subject_code: str,
        values_by_code: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        metrics = []
        for metric_key, metric_label, weight, direction, unit in specs:
            values = {
                code: payload.get(metric_key)
                for code, payload in values_by_code.items()
            }
            metrics.append(
                _industry_metric(
                    key=metric_key,
                    label=metric_label,
                    weight=weight,
                    direction=direction,
                    unit=unit,
                    subject_code=subject_code,
                    values=values,
                )
            )
        return _factor_packet(key, label, metrics)

    def _valuation_factor(
        self,
        subject_code: str,
        valuation_by_code: dict[str, dict[str, Any]],
        history: pd.DataFrame,
    ) -> dict[str, Any]:
        current = valuation_by_code.get(subject_code) or {}
        pe = _number(current.get("pe_ttm"))
        pe_available = pe is not None and pe > 0
        weights = (
            {
                "pe_history": 25.0,
                "pe_industry": 25.0,
                "pb_history": 15.0,
                "pb_industry": 15.0,
                "ps_history": 10.0,
                "ps_industry": 10.0,
            }
            if pe_available
            else {
                "pe_history": 0.0,
                "pe_industry": 0.0,
                "pb_history": 30.0,
                "pb_industry": 30.0,
                "ps_history": 20.0,
                "ps_industry": 20.0,
            }
        )
        metrics: list[dict[str, Any]] = []
        for prefix, field, label in (
            ("pe", "pe_ttm", "PE TTM"),
            ("pb", "pb", "PB"),
            ("ps", "ps_ttm", "PS TTM"),
        ):
            current_value = _number(current.get(field))
            industry_values = {
                code: _number(row.get(field))
                for code, row in valuation_by_code.items()
            }
            industry_values = {
                code: value
                for code, value in industry_values.items()
                if value is not None and value > 0
            }
            metrics.append(
                _industry_metric(
                    key=f"{prefix}_industry",
                    label=f"{label}行业反向分位",
                    weight=weights[f"{prefix}_industry"],
                    direction="lower",
                    unit="倍",
                    subject_code=subject_code,
                    values=industry_values,
                )
            )
            metrics.append(
                _history_metric(
                    key=f"{prefix}_history",
                    label=f"{label}五年历史反向分位",
                    weight=weights[f"{prefix}_history"],
                    unit="倍",
                    current=current_value,
                    values=_positive_history(history, field),
                )
            )
        ordered_keys = [
            "pe_history",
            "pe_industry",
            "pb_history",
            "pb_industry",
            "ps_history",
            "ps_industry",
        ]
        metrics.sort(key=lambda item: ordered_keys.index(item["key"]))
        factor = _factor_packet("valuation", "估值水平", metrics)
        factor["peWeightTransferred"] = not pe_available
        return factor

    def _query_frame(self, api_name: str, **params: Any) -> pd.DataFrame:
        key = json.dumps(
            [api_name, sorted(params.items())],
            ensure_ascii=False,
            default=str,
        )
        now = time.monotonic()
        with self._lock:
            cached = self._frame_cache.get(key)
            if cached and cached[0] > now:
                return cached[1].copy()
        frame = self.client.query(api_name, **params)
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame(frame or [])
        with self._lock:
            self._frame_cache[key] = (
                time.monotonic() + self.batch_cache_seconds,
                frame.copy(),
            )
        return frame


def _canonical_a_share(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    if not canonical.endswith((".SS", ".SZ", ".BJ")):
        raise ValueError("行业五维对比目前只支持 A 股证券")
    return canonical


def _to_tushare_symbol(symbol: str) -> str:
    return symbol[:-3] + ".SH" if symbol.endswith(".SS") else symbol


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [dict(item) for item in frame.to_dict(orient="records")]


def _latest_rows(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ts_code" not in frame:
        return {}
    data = frame.copy()
    data["ts_code"] = data["ts_code"].astype(str).str.upper()
    if "report_type" in data:
        report_type = data["report_type"].astype(str)
        preferred = data[report_type.isin({"1", "1.0", "01"})]
        if not preferred.empty:
            preferred_codes = set(preferred["ts_code"])
            data = pd.concat(
                [
                    preferred,
                    data[~data["ts_code"].isin(preferred_codes)],
                ],
                ignore_index=True,
            )
    sort_columns = [
        column
        for column in ("ts_code", "update_flag", "ann_date")
        if column in data
    ]
    if sort_columns:
        data = data.sort_values(sort_columns, na_position="first")
    data = data.drop_duplicates("ts_code", keep="last")
    return {
        str(row["ts_code"]).upper(): dict(row)
        for row in data.to_dict(orient="records")
    }


def _is_a_share_code(value: Any) -> bool:
    code = str(value or "").upper()
    return code.endswith((".SH", ".SZ", ".BJ")) and len(code.split(".", 1)[0]) == 6


def _is_st_name(value: Any) -> bool:
    name = str(value or "").upper().replace(" ", "")
    return "ST" in name


def _member_active_on(item: dict[str, Any], period: str) -> bool:
    joined = str(item.get("in_date") or "").strip()
    removed = str(item.get("out_date") or "").strip()
    if joined and joined > period:
        return False
    return not removed or removed > period


def _recent_quarter_periods(as_of: date, *, count: int) -> list[str]:
    quarter = (as_of.month - 1) // 3 + 1
    end_month = quarter * 3
    end_day = calendar.monthrange(as_of.year, end_month)[1]
    period = date(as_of.year, end_month, end_day)
    if period > as_of:
        period_text = _shift_quarter(period.strftime("%Y%m%d"), -1)
    else:
        period_text = period.strftime("%Y%m%d")
    return [_shift_quarter(period_text, -offset) for offset in range(count)]


def _shift_quarter(period: str, offset: int) -> str:
    year = int(period[:4])
    month = int(period[4:6])
    quarter_index = year * 4 + (month // 3 - 1) + offset
    target_year, target_quarter = divmod(quarter_index, 4)
    target_month = (target_quarter + 1) * 3
    target_day = calendar.monthrange(target_year, target_month)[1]
    return f"{target_year:04d}{target_month:02d}{target_day:02d}"


def _last_completed_fy(period: str) -> str:
    year = int(period[:4])
    return period if period.endswith("1231") else f"{year - 1}1231"


def _iso_period(period: str) -> str:
    return f"{period[:4]}-{period[4:6]}-{period[6:8]}"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    top = _number(numerator)
    bottom = _number(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _ratio_pct(numerator: Any, denominator: Any) -> float | None:
    value = _ratio(numerator, denominator)
    return value * 100.0 if value is not None else None


def _growth_pct(current: Any, comparable: Any) -> float | None:
    current_value = _number(current)
    comparable_value = _number(comparable)
    if (
        current_value is None
        or comparable_value is None
        or comparable_value <= 0
        or current_value < 0
    ):
        return None
    return (current_value / comparable_value - 1.0) * 100.0


def _difference(current: Any, previous: Any) -> float | None:
    current_value = _number(current)
    previous_value = _number(previous)
    if current_value is None or previous_value is None:
        return None
    return current_value - previous_value


def _average_positive(first: Any, second: Any) -> float | None:
    left = _number(first)
    right = _number(second)
    if left is None or right is None:
        return None
    average = (left + right) / 2.0
    return average if average > 0 else None


def _sum_available(values: Iterable[Any]) -> float | None:
    numbers = [_number(value) for value in values]
    available = [value for value in numbers if value is not None]
    return sum(available) if available else None


def _short_interest_bearing_debt(getter: Any) -> float | None:
    return _sum_available(
        getter(field)
        for field in ("st_borr", "st_bonds_payable", "non_cur_liab_due_1y")
    )


def _interest_bearing_debt(getter: Any) -> float | None:
    return _sum_available(
        getter(field)
        for field in (
            "st_borr",
            "st_bonds_payable",
            "non_cur_liab_due_1y",
            "lt_borr",
            "bond_payable",
            "lease_liab",
        )
    )


def _excess_cash(cash: Any, revenue_ttm: Any) -> float | None:
    cash_value = _number(cash)
    revenue_value = _number(revenue_ttm)
    if cash_value is None or revenue_value is None:
        return None
    return max(
        cash_value - revenue_value * _MIN_OPERATING_CASH_REVENUE_RATIO,
        0.0,
    )


def _invested_capital(
    equity: Any, debt: Any, excess_cash: Any
) -> float | None:
    equity_value = _number(equity)
    debt_value = _number(debt)
    cash_value = _number(excess_cash)
    if equity_value is None or debt_value is None or cash_value is None:
        return None
    result = equity_value + debt_value - cash_value
    return result if result > 0 else None


def _percentile_rank(value: float, values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    less = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    average_rank = less + (equal + 1.0) / 2.0
    return (average_rank - 1.0) / (len(values) - 1.0) * 100.0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _sample_percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, fraction))
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return (
        ordered[lower_index] * (1.0 - weight)
        + ordered[upper_index] * weight
    )


def _comparison_summary(
    *,
    key: str,
    label: str,
    unit: str,
    subject_code: str,
    values: dict[str, float | None],
    data_date: str,
    positive_only: bool = False,
) -> dict[str, Any]:
    subject = _number(values.get(subject_code))
    sample = [
        number
        for value in values.values()
        if (number := _number(value)) is not None
        and (not positive_only or number > 0)
    ]
    if positive_only and (subject is None or subject <= 0):
        subject = None
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "subject": _rounded(subject),
        "industryP25": _rounded(_sample_percentile(sample, 0.25)),
        "industryMedian": _rounded(_sample_percentile(sample, 0.50)),
        "industryP75": _rounded(_sample_percentile(sample, 0.75)),
        "sampleSize": len(sample),
        "dataDate": data_date,
        "status": (
            "available"
            if subject is not None and len(sample) >= _MIN_SAMPLE_SIZE
            else "insufficient_sample"
            if subject is not None
            else "subject_missing"
        ),
    }


def _industry_metric(
    *,
    key: str,
    label: str,
    weight: float,
    direction: str,
    unit: str,
    subject_code: str,
    values: dict[str, float | None],
) -> dict[str, Any]:
    subject = _number(values.get(subject_code))
    sample = [
        number
        for value in values.values()
        if (number := _number(value)) is not None
    ]
    percentile = (
        _percentile_rank(subject, sample) if subject is not None else None
    )
    score = (
        (100.0 - percentile if direction == "lower" else percentile)
        if percentile is not None and len(sample) >= _MIN_SAMPLE_SIZE
        else None
    )
    status = (
        "subject_missing"
        if subject is None
        else "insufficient_sample"
        if len(sample) < _MIN_SAMPLE_SIZE
        else "partial"
        if len(sample) < _FULL_SAMPLE_SIZE
        else "available"
    )
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "direction": direction,
        "unit": unit,
        "comparisonType": "industry",
        "rawValue": _rounded(subject),
        "industryMedian": _rounded(_median(sample)),
        "industryPercentile": _rounded(percentile),
        "score": _rounded(score),
        "sampleSize": len(sample),
        "status": status,
    }


def _positive_history(frame: pd.DataFrame, field: str) -> list[float]:
    if frame.empty or field not in frame:
        return []
    values = pd.to_numeric(frame[field], errors="coerce")
    return [
        float(value)
        for value in values.dropna().tolist()
        if math.isfinite(float(value)) and float(value) > 0
    ][-_HISTORY_DAYS:]


def _history_metric(
    *,
    key: str,
    label: str,
    weight: float,
    unit: str,
    current: float | None,
    values: list[float],
) -> dict[str, Any]:
    valid_current = current if current is not None and current > 0 else None
    percentile = (
        sum(value <= valid_current for value in values) / len(values) * 100.0
        if valid_current is not None and values
        else None
    )
    score = (
        100.0 - percentile
        if percentile is not None and len(values) >= _MIN_HISTORY_DAYS
        else None
    )
    status = (
        "subject_missing"
        if valid_current is None
        else "insufficient_history"
        if len(values) < _MIN_HISTORY_DAYS
        else "available"
    )
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "direction": "lower",
        "unit": unit,
        "comparisonType": "history",
        "rawValue": _rounded(valid_current),
        "historyMedian": _rounded(_median(values)),
        "historyPercentile": _rounded(percentile),
        "score": _rounded(score),
        "sampleSize": len(values),
        "status": status,
    }


def _factor_packet(
    key: str, label: str, metrics: list[dict[str, Any]]
) -> dict[str, Any]:
    total_weight = sum(float(metric.get("weight") or 0) for metric in metrics)
    valid = [
        metric
        for metric in metrics
        if metric.get("score") is not None and float(metric.get("weight") or 0) > 0
    ]
    valid_weight = sum(float(metric["weight"]) for metric in valid)
    coverage = valid_weight / total_weight * 100.0 if total_weight else 0.0
    weighted = (
        sum(float(metric["score"]) * float(metric["weight"]) for metric in valid)
        / valid_weight
        if valid_weight
        else None
    )
    score = weighted if coverage >= 60.0 else None
    status = (
        "available"
        if score is not None and coverage >= 80.0
        else "partial"
        if score is not None
        else "insufficient_coverage"
    )
    return {
        "key": key,
        "label": label,
        "score": _rounded(score),
        "coveragePct": _rounded(coverage),
        "status": status,
        "state": _factor_state(score),
        "metrics": metrics,
    }


def _factor_state(score: float | None) -> str:
    if score is None:
        return "数据不足"
    if score >= 80:
        return "行业领先"
    if score >= 65:
        return "相对较强"
    if score >= 35:
        return "行业中游"
    if score >= 20:
        return "相对偏弱"
    return "行业靠后"


def _rounded(value: Any) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))
