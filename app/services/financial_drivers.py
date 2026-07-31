from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any

from app.catalog import normalize_symbol
from app.db import Database
from app.services.filings import AShareFilingService
from app.utils import utc_now


class FinancialDriverAnalysisService:
    """Deterministically decompose reported profit and cash-flow changes.

    The service deliberately separates mathematical statement bridges from
    business-cause attribution.  A margin bridge can explain where the change
    sits in the accounts, but not whether price, mix, input cost or another
    operating cause produced it.
    """

    METHOD = "deterministic_financial_driver_v2_filing_evidence"

    def __init__(
        self,
        database: Database,
        filings: AShareFilingService | None = None,
    ):
        self.database = database
        self.filings = filings

    def get_packet(self, symbol: str, persist: bool = True) -> dict[str, Any]:
        canonical = normalize_symbol(symbol)
        details = self.database.list_financial_statement_details(
            canonical, limit=60
        )
        periods = _group_periods(details)
        latest = next(
            (item for item in periods if "income" in item["statement_coverage"]),
            periods[0] if periods else None,
        )
        if latest is None:
            return self._unavailable(
                canonical,
                "尚未取得可用于拆解的利润表、资产负债表和现金流量表明细。",
            )
        comparable = _find_comparable(latest, periods)
        if comparable is None:
            return self._unavailable(
                canonical,
                "已取得最新详细财务报表，但尚未找到上一年度同类报告期。",
                latest,
            )

        packet = self._analyze(canonical, latest, comparable)
        if self.filings is not None and canonical.endswith((".SS", ".SZ")):
            report_period = latest.get("report_date")
            try:
                filing_evidence = self.filings.get_packet(
                    canonical,
                    report_period=report_period,
                    persist=persist,
                )
                if filing_evidence.get("status") != "available" and report_period:
                    filing_evidence = self.filings.ensure_report(
                        canonical, report_period
                    )
                self._attach_filing_evidence(packet, filing_evidence)
            except Exception:
                packet["filing_evidence"] = {
                    "type": "filing_cause_evidence",
                    "symbol": canonical,
                    "status": "insufficient",
                    "summary": "当前报告期的公司财报原文证据尚未完成入库。",
                    "explicit_company_explanations": [],
                    "reported_facts": [],
                    "boundary": "不使用新闻标题或模型常识替代公司原文。",
                }
                packet["company_explanations"] = []
        if persist:
            fingerprint = _fingerprint(packet)
            saved = self.database.save_financial_driver_snapshot(packet, fingerprint)
            packet["snapshot_id"] = saved["id"]
            packet["snapshot_created_at"] = saved["created_at"]
            self._index_common_knowledge(packet)
        return packet

    @staticmethod
    def _attach_filing_evidence(
        packet: dict[str, Any], filing_evidence: dict[str, Any]
    ) -> None:
        explanations = list(
            filing_evidence.get("explicit_company_explanations") or []
        )[:10]
        packet["filing_evidence"] = filing_evidence
        packet["company_explanations"] = explanations
        packet.setdefault("coverage", {})["company_filing"] = {
            "status": filing_evidence.get("status"),
            "report_period": (
                filing_evidence.get("document") or {}
            ).get("report_period"),
            "explicit_explanations": len(explanations),
            "reported_facts": len(filing_evidence.get("reported_facts") or []),
        }
        if explanations:
            explained_labels = "、".join(
                dict.fromkeys(
                    str(item.get("label") or "相关科目")
                    for item in explanations[:4]
                )
            )
            packet["summary"] += (
                f" 公司财报原文已对{explained_labels}给出明确说明；"
                "这些说明属于管理层披露，尚不等于独立验证的唯一因果。"
            )
            packet["review_points"] = [
                "把公司原文解释与后续报告、分业务数据和现金流变化交叉验证。",
                *packet.get("review_points", []),
            ][:4]
        packet["boundary"] += (
            " 公司报告中的原因说明会单列为管理层解释，"
            "不会提升为独立验证的确定因果。"
        )

    def refresh_symbols(self, symbols: list[str]) -> dict[str, Any]:
        results = []
        for symbol in sorted({normalize_symbol(item) for item in symbols}):
            packet = self.get_packet(symbol)
            results.append(
                {
                    "symbol": symbol,
                    "status": packet["status"],
                    "report_date": (packet.get("latest_period") or {}).get(
                        "report_date"
                    ),
                    "overall_label": packet.get("overall_label"),
                }
            )
        return {
            "requested": len(results),
            "completed": sum(item["status"] == "available" for item in results),
            "results": results,
        }

    def _unavailable(
        self,
        symbol: str,
        summary: str,
        latest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "financial_drivers",
            "symbol": symbol,
            "name": (latest or {}).get("name") or symbol,
            "status": "insufficient",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "summary": summary,
            "latest_period": _public_period(latest) if latest else None,
            "comparable_period": None,
            "confirmed_mechanical_drivers": [],
            "plausible_clues": [],
            "unresolved_causes": [
                "缺少同类报告期时，不用相邻累计报告期或模型估算替代同比拆解。"
            ],
            "review_points": ["等待或补齐上一年度同类报告期的详细三表数据。"],
            "boundary": (
                "利润与现金流驱动拆解只使用已披露科目；缺失科目不会由模型补写。"
            ),
        }

    def _analyze(
        self,
        symbol: str,
        latest: dict[str, Any],
        comparable: dict[str, Any],
    ) -> dict[str, Any]:
        current = latest["fields"]
        previous = comparable["fields"]
        currency = latest.get("currency") or "CNY"

        revenue = _num(current.get("revenue"))
        previous_revenue = _num(previous.get("revenue"))
        net_profit = _num(current.get("parent_net_profit"))
        previous_net_profit = _num(previous.get("parent_net_profit"))
        direct_cost = _first_number(
            current.get("operating_cost"), current.get("cost_of_revenue")
        )
        previous_direct_cost = _first_number(
            previous.get("operating_cost"), previous.get("cost_of_revenue")
        )
        gross_profit = _first_number(
            current.get("gross_profit"), _difference(revenue, direct_cost)
        )
        previous_gross_profit = _first_number(
            previous.get("gross_profit"),
            _difference(previous_revenue, previous_direct_cost),
        )
        gross_margin = _ratio_pct(gross_profit, revenue)
        previous_gross_margin = _ratio_pct(
            previous_gross_profit, previous_revenue
        )
        gross_margin_change = _difference(gross_margin, previous_gross_margin)
        revenue_growth = _pct_change(revenue, previous_revenue)
        net_profit_change = _difference(net_profit, previous_net_profit)
        net_profit_growth = _pct_change(net_profit, previous_net_profit)
        gross_profit_change = _difference(gross_profit, previous_gross_profit)

        confirmed: list[dict[str, Any]] = []
        if net_profit_change is not None:
            confirmed.append(
                _driver(
                    "net_profit_change",
                    "归母净利润变化",
                    net_profit_change,
                    currency,
                    (
                        f"归母净利润较上一年度同类报告期变化"
                        f" {_money(net_profit_change, currency)}。"
                    ),
                )
            )
        if (
            revenue is not None
            and previous_revenue is not None
            and gross_margin is not None
            and previous_gross_margin is not None
        ):
            scale_effect = round(
                (revenue - previous_revenue) * previous_gross_margin / 100.0, 2
            )
            margin_effect = round(
                revenue * (gross_margin - previous_gross_margin) / 100.0, 2
            )
            confirmed.extend(
                [
                    _driver(
                        "gross_profit_revenue_scale_effect",
                        "收入规模对毛利的机械影响",
                        scale_effect,
                        currency,
                        (
                            "按可比期毛利率不变静态测算，收入规模变化对应毛利"
                            f" {_money(scale_effect, currency)}。"
                        ),
                    ),
                    _driver(
                        "gross_profit_margin_effect",
                        "毛利率变化对毛利的机械影响",
                        margin_effect,
                        currency,
                        (
                            f"毛利率由 {_fmt(previous_gross_margin)}% 变为"
                            f" {_fmt(gross_margin)}%，按本期收入静态测算对应毛利"
                            f" {_money(margin_effect, currency)}。"
                        ),
                    ),
                ]
            )

        expense_specs = (
            ("sales_expense", "销售费用"),
            ("management_expense", "管理费用"),
            ("selling_general_admin_expense", "销售及管理费用"),
            ("research_expense", "研发费用"),
            ("finance_expense", "财务费用"),
            ("operating_tax_surcharges", "税金及附加"),
        )
        expense_analysis = []
        known_expense_effect = 0.0
        has_known_expense_effect = False
        for key, label in expense_specs:
            current_value = _num(current.get(key))
            previous_value = _num(previous.get(key))
            if current_value is None and previous_value is None:
                continue
            change = _difference(current_value, previous_value)
            profit_effect = -change if change is not None else None
            ratio = _ratio_pct(current_value, revenue)
            previous_ratio = _ratio_pct(previous_value, previous_revenue)
            ratio_change = _difference(ratio, previous_ratio)
            item = {
                "key": key,
                "label": label,
                "current": current_value,
                "comparable": previous_value,
                "change_amount": change,
                "profit_effect_amount": profit_effect,
                "current_ratio_pct": ratio,
                "comparable_ratio_pct": previous_ratio,
                "ratio_change_pp": ratio_change,
            }
            expense_analysis.append(item)
            if profit_effect is not None:
                known_expense_effect += profit_effect
                has_known_expense_effect = True
                confirmed.append(
                    _driver(
                        f"{key}_profit_effect",
                        f"{label}变化的机械影响",
                        profit_effect,
                        currency,
                        (
                            f"{label}较可比期变化 {_money(change, currency)}，"
                            f"对应利润方向的机械影响为 {_money(profit_effect, currency)}；"
                            f"费用率变化 {_signed(ratio_change)} 个百分点。"
                        ),
                    )
                )

        operating_profit = _num(current.get("operating_profit"))
        previous_operating_profit = _num(previous.get("operating_profit"))
        operating_profit_change = _difference(
            operating_profit, previous_operating_profit
        )
        explained_operating_change = None
        unexplained_operating_change = None
        if gross_profit_change is not None:
            explained_operating_change = round(
                gross_profit_change
                + (known_expense_effect if has_known_expense_effect else 0.0),
                2,
            )
        if operating_profit_change is not None and explained_operating_change is not None:
            unexplained_operating_change = round(
                operating_profit_change - explained_operating_change, 2
            )

        deducted_profit = _num(current.get("deducted_parent_net_profit"))
        previous_deducted_profit = _num(
            previous.get("deducted_parent_net_profit")
        )
        nonrecurring_gap = _difference(net_profit, deducted_profit)
        previous_nonrecurring_gap = _difference(
            previous_net_profit, previous_deducted_profit
        )
        income_tax = _num(current.get("income_tax"))
        previous_income_tax = _num(previous.get("income_tax"))

        working_capital = []
        plausible: list[dict[str, Any]] = []
        for key, label in (
            ("accounts_receivable", "应收账款"),
            ("inventory", "存货"),
            ("accounts_payable", "应付账款"),
        ):
            current_value = _num(current.get(key))
            previous_value = _num(previous.get(key))
            growth = _pct_change(current_value, previous_value)
            item = {
                "key": key,
                "label": label,
                "current": current_value,
                "comparable": previous_value,
                "growth_pct": growth,
                "growth_minus_revenue_pp": _difference(growth, revenue_growth),
            }
            working_capital.append(item)
            gap = item["growth_minus_revenue_pp"]
            if key in {"accounts_receivable", "inventory"} and gap is not None and gap >= 5:
                plausible.append(
                    _clue(
                        key,
                        f"{label}增速快于收入",
                        (
                            f"{label}同比 {_signed(growth)}%，收入同比"
                            f" {_signed(revenue_growth)}%，快 {_fmt(gap)} 个百分点。"
                        ),
                    )
                )
            if key == "accounts_payable" and gap is not None and abs(gap) >= 10:
                plausible.append(
                    _clue(
                        key,
                        "应付账款变化与收入不同步",
                        (
                            f"应付账款同比 {_signed(growth)}%，与收入增速相差"
                            f" {_fmt(gap)} 个百分点；可能反映付款节奏变化。"
                        ),
                    )
                )

        operating_cashflow = _num(current.get("operating_cashflow"))
        previous_operating_cashflow = _num(previous.get("operating_cashflow"))
        cash_received = _num(current.get("cash_received_from_sales"))
        previous_cash_received = _num(previous.get("cash_received_from_sales"))
        capex = _num(current.get("capital_expenditure_proxy"))
        previous_capex = _num(previous.get("capital_expenditure_proxy"))
        cash_metrics = {
            "operating_cashflow": operating_cashflow,
            "comparable_operating_cashflow": previous_operating_cashflow,
            "operating_cashflow_change": _difference(
                operating_cashflow, previous_operating_cashflow
            ),
            "operating_cashflow_change_pct": _pct_change(
                operating_cashflow, previous_operating_cashflow
            ),
            "operating_cashflow_to_net_profit": _ratio(
                operating_cashflow, net_profit
            ),
            "comparable_operating_cashflow_to_net_profit": _ratio(
                previous_operating_cashflow, previous_net_profit
            ),
            "cash_received_from_sales": cash_received,
            "cash_received_from_sales_to_revenue_pct": _ratio_pct(
                cash_received, revenue
            ),
            "comparable_cash_received_from_sales_to_revenue_pct": _ratio_pct(
                previous_cash_received, previous_revenue
            ),
            "investing_cashflow": _num(current.get("investing_cashflow")),
            "comparable_investing_cashflow": _num(
                previous.get("investing_cashflow")
            ),
            "financing_cashflow": _num(current.get("financing_cashflow")),
            "comparable_financing_cashflow": _num(
                previous.get("financing_cashflow")
            ),
            "capital_expenditure_proxy": capex,
            "comparable_capital_expenditure_proxy": previous_capex,
            "capital_expenditure_to_revenue_pct": _ratio_pct(capex, revenue),
        }
        cash_ratio = cash_metrics["operating_cashflow_to_net_profit"]
        previous_cash_ratio = cash_metrics[
            "comparable_operating_cashflow_to_net_profit"
        ]
        cashflow_change = cash_metrics["operating_cashflow_change"]
        if cash_ratio is not None and (
            cash_ratio < 0
            or (
                previous_cash_ratio is not None
                and cash_ratio < previous_cash_ratio - 0.15
            )
        ):
            if cash_ratio < 0:
                clue_label = "经营现金流与利润方向相反"
            elif isinstance(cashflow_change, (int, float)) and cashflow_change < 0:
                clue_label = "经营现金流覆盖率下降"
            else:
                clue_label = "利润增速快于经营现金流"
            plausible.append(
                _clue(
                    "operating_cashflow_coverage",
                    clue_label,
                    (
                        f"经营现金流/归母净利润由 {_fmt(previous_cash_ratio)}"
                        f" 变为 {_fmt(cash_ratio)}。"
                    ),
                )
            )
        sales_cash_ratio = cash_metrics[
            "cash_received_from_sales_to_revenue_pct"
        ]
        previous_sales_cash_ratio = cash_metrics[
            "comparable_cash_received_from_sales_to_revenue_pct"
        ]
        sales_cash_ratio_change = _difference(
            sales_cash_ratio, previous_sales_cash_ratio
        )
        cash_metrics["cash_received_from_sales_ratio_change_pp"] = (
            sales_cash_ratio_change
        )
        if sales_cash_ratio_change is not None and sales_cash_ratio_change <= -5:
            plausible.append(
                _clue(
                    "sales_cash_collection",
                    "销售收现率下降",
                    (
                        f"销售收现/收入由 {_fmt(previous_sales_cash_ratio)}%"
                        f" 变为 {_fmt(sales_cash_ratio)}%，下降"
                        f" {_fmt(abs(sales_cash_ratio_change))} 个百分点。"
                    ),
                )
            )

        unresolved = [
            "毛利率变化已经量化，但价格、产品结构、采购成本或交付结构中的具体原因尚未由三表科目确认。",
            "应收、存货和现金流变化只能提供营运资金线索，季节性、回款安排与业务节奏仍需公告附注验证。",
        ]
        if unexplained_operating_change is not None and abs(unexplained_operating_change) > max(
            1.0, abs(operating_profit_change or 0) * 0.05
        ):
            unresolved.append(
                "已列示毛利和费用科目仍不能完全解释营业利润变化；差额可能包含其他收益、减值、公允价值或未单列科目。"
            )
        if nonrecurring_gap is not None:
            plausible.append(
                _clue(
                    "reported_vs_deducted_profit",
                    "归母净利润与扣非净利润存在差额",
                    (
                        f"本期差额 {_money(nonrecurring_gap, currency)}，"
                        f"可比期差额 {_money(previous_nonrecurring_gap, currency)}；"
                        "差额需要结合非经常性损益明细解释。"
                    ),
                )
            )

        overall_label = _overall_label(
            net_profit_change,
            cash_metrics["operating_cashflow_change"],
            confirmed,
        )
        coverage = {
            "latest_statement_types": latest["statement_coverage"],
            "comparable_statement_types": comparable["statement_coverage"],
            "latest_available_fields": sum(
                value is not None for value in current.values()
            ),
            "comparable_available_fields": sum(
                value is not None for value in previous.values()
            ),
            "comparable_basis": "上一年度同类报告期",
        }
        confidence = (
            "high"
            if set(latest["statement_coverage"])
            == set(comparable["statement_coverage"])
            == {"income", "balance", "cashflow"}
            else "medium"
        )
        return {
            "type": "financial_drivers",
            "symbol": symbol,
            "name": latest.get("name") or symbol,
            "status": "available",
            "generated_at": utc_now(),
            "method": self.METHOD,
            "overall_label": overall_label,
            "confidence": confidence,
            "summary": (
                f"{latest.get('report_date_name')}相对{comparable.get('report_date_name')}，"
                f"归母净利润变化 {_money(net_profit_change, currency)}；"
                "当前拆解区分已确认的报表机械影响、可疑线索和仍未确认的经营原因。"
            ),
            "latest_period": _public_period(
                latest,
                derived={
                    "revenue": revenue,
                    "revenue_growth_pct": revenue_growth,
                    "gross_profit": gross_profit,
                    "gross_margin_pct": gross_margin,
                    "parent_net_profit": net_profit,
                    "net_profit_growth_pct": net_profit_growth,
                    "operating_profit": operating_profit,
                    "deducted_parent_net_profit": deducted_profit,
                    "income_tax": income_tax,
                },
            ),
            "comparable_period": _public_period(
                comparable,
                derived={
                    "revenue": previous_revenue,
                    "gross_profit": previous_gross_profit,
                    "gross_margin_pct": previous_gross_margin,
                    "parent_net_profit": previous_net_profit,
                    "operating_profit": previous_operating_profit,
                    "deducted_parent_net_profit": previous_deducted_profit,
                    "income_tax": previous_income_tax,
                },
            ),
            "profit_bridge": {
                "gross_profit_change": gross_profit_change,
                "gross_margin_change_pp": gross_margin_change,
                "operating_profit_change": operating_profit_change,
                "known_gross_profit_and_expense_effect": explained_operating_change,
                "unexplained_operating_profit_change": unexplained_operating_change,
                "net_profit_change": net_profit_change,
                "nonrecurring_gap": nonrecurring_gap,
                "comparable_nonrecurring_gap": previous_nonrecurring_gap,
                "currency": currency,
            },
            "expense_analysis": expense_analysis,
            "working_capital_analysis": working_capital,
            "cashflow_analysis": cash_metrics,
            "confirmed_mechanical_drivers": confirmed,
            "plausible_clues": plausible,
            "unresolved_causes": unresolved,
            "review_points": [
                "对照公告附注核对毛利率变化对应的价格、产品结构、成本和交付原因。",
                "核对应收账款、存货、合同负债及销售收现变化，区分季节性与持续占用。",
                "核对减值、其他收益、公允价值和非经常性损益，解释营业利润桥接差额。",
            ],
            "coverage": coverage,
            "interpretation_rules": [
                "只比较上一年度同类报告期，不把累计中报与一季报误写成环比。",
                "机械驱动是报表恒等式或科目变化，不等于已证明的业务因果。",
                "营运资金和现金流仅提供复核线索，不能由相关性直接推断经营恶化。",
            ],
            "boundary": (
                "该分析用于定位利润与现金流变化落在哪些报表科目；"
                "精确业务原因仍需公告原文、附注和分业务披露确认，"
                "不构成利润预测、目标价或交易指令。"
            ),
        }

    def _index_common_knowledge(self, packet: dict[str, Any]) -> None:
        source_key = f"financial-drivers:{packet['symbol']}"
        document_id = "common-" + hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()[:24]
        confirmed = "\n".join(
            f"- {item['statement']}"
            for item in packet.get("confirmed_mechanical_drivers", [])[:8]
        ) or "- 尚无可确认的机械拆解。"
        clues = "\n".join(
            f"- {item['label']}：{item['evidence']}"
            for item in packet.get("plausible_clues", [])[:8]
        ) or "- 尚未形成显著线索。"
        unresolved = "\n".join(
            f"- {item}" for item in packet.get("unresolved_causes", [])[:6]
        )
        company_explanations = "\n".join(
            f"- {item.get('label')}：{item.get('excerpt')}"
            for item in packet.get("company_explanations", [])[:8]
        ) or "- 当前报告期尚未入库公司明确原因说明。"
        content = (
            f"# {packet['name']}利润与现金流驱动分析\n\n"
            f"证券代码：{packet['symbol']}\n\n"
            f"最新报告期：{(packet.get('latest_period') or {}).get('report_date_name')}\n\n"
            f"可比报告期：{(packet.get('comparable_period') or {}).get('report_date_name')}\n\n"
            f"结论：{packet.get('overall_label')}\n\n"
            f"## 已确认的机械拆解\n\n{confirmed}\n\n"
            f"## 可疑线索\n\n{clues}\n\n"
            f"## 公司财报原文解释\n\n{company_explanations}\n\n"
            f"## 仍未确认的原因\n\n{unresolved}\n\n"
            f"## 证据边界\n\n{packet.get('boundary')}"
        )
        self.database.upsert_knowledge_document(
            document_id=document_id,
            owner_user_id=None,
            scope="common",
            title=f"{packet['name']}利润与现金流驱动分析",
            original_name=f"{packet['symbol']}-financial-drivers.md",
            mime_type="text/markdown",
            content=content,
            source_key=source_key,
        )


def _group_periods(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in details:
        key = (item["report_date"], item["report_type"])
        period = grouped.setdefault(
            key,
            {
                "symbol": item["symbol"],
                "name": item.get("name") or item["symbol"],
                "report_date": item["report_date"],
                "report_type": item["report_type"],
                "report_date_name": item.get("report_date_name"),
                "notice_date": item.get("notice_date"),
                "currency": item.get("currency"),
                "fiscal_period": item.get("fiscal_period"),
                "period_basis": item.get("period_basis"),
                "statement_coverage": [],
                "fields": {},
            },
        )
        period["statement_coverage"].append(item["statement_type"])
        period["fields"].update(item.get("fields") or {})
    for period in grouped.values():
        period["statement_coverage"] = sorted(set(period["statement_coverage"]))
    return sorted(grouped.values(), key=lambda item: item["report_date"], reverse=True)


def _find_comparable(
    current: dict[str, Any], periods: list[dict[str, Any]]
) -> dict[str, Any] | None:
    try:
        current_date = date.fromisoformat(current["report_date"])
    except (TypeError, ValueError):
        return None
    matches = []
    for item in periods:
        if item is current or item.get("fiscal_period") != current.get("fiscal_period"):
            continue
        try:
            older = date.fromisoformat(item["report_date"])
        except (TypeError, ValueError):
            continue
        if older >= current_date:
            continue
        delta = (current_date - older).days
        if 300 <= delta <= 430:
            matches.append((abs(delta - 365), item))
    return min(matches, key=lambda pair: pair[0])[1] if matches else None


def _public_period(
    period: dict[str, Any] | None, derived: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if period is None:
        return None
    return {
        key: period.get(key)
        for key in (
            "symbol",
            "name",
            "report_date",
            "report_type",
            "report_date_name",
            "notice_date",
            "currency",
            "fiscal_period",
            "period_basis",
            "statement_coverage",
        )
    } | (derived or {})


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _num(value)
        if number is not None:
            return number
    return None


def _difference(current: Any, previous: Any) -> float | None:
    current_number = _num(current)
    previous_number = _num(previous)
    if current_number is None or previous_number is None:
        return None
    return round(current_number - previous_number, 6)


def _pct_change(current: Any, previous: Any) -> float | None:
    current_number = _num(current)
    previous_number = _num(previous)
    if current_number is None or previous_number in (None, 0):
        return None
    return round((current_number / previous_number - 1.0) * 100.0, 3)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_number = _num(numerator)
    denominator_number = _num(denominator)
    if numerator_number is None or denominator_number in (None, 0):
        return None
    return round(numerator_number / denominator_number, 3)


def _ratio_pct(numerator: Any, denominator: Any) -> float | None:
    numerator_number = _num(numerator)
    denominator_number = _num(denominator)
    if numerator_number is None or denominator_number in (None, 0):
        return None
    return round(numerator_number / denominator_number * 100.0, 3)


def _driver(
    key: str,
    label: str,
    amount: float,
    currency: str,
    statement: str,
) -> dict[str, Any]:
    static_counterfactual = key in {
        "gross_profit_revenue_scale_effect",
        "gross_profit_margin_effect",
    }
    return {
        "key": key,
        "label": label,
        "attribution_level": "confirmed_mechanical_driver",
        "calculation_nature": (
            "static_counterfactual"
            if static_counterfactual
            else "reported_statement_bridge"
        ),
        "amount": round(amount, 2),
        "currency": currency,
        "direction": "positive" if amount > 0 else "negative" if amount < 0 else "neutral",
        "statement": statement,
        "interpretation_boundary": (
            "这是保持另一项毛利桥变量不变的静态反事实测算，只用于定位报表量级；"
            "不能写成已经确认的经营原因、直接因果或股价驱动。"
            if static_counterfactual
            else "这是报表科目变化的机械桥接，不等于公司已经确认的经营原因或股价驱动。"
        ),
    }


def _clue(key: str, label: str, evidence: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "attribution_level": "plausible_clue",
        "evidence": evidence,
    }


def _overall_label(
    net_profit_change: float | None,
    operating_cashflow_change: float | None,
    drivers: list[dict[str, Any]],
) -> str:
    negative_drivers = sum(item.get("direction") == "negative" for item in drivers)
    if (
        net_profit_change is not None
        and net_profit_change < 0
        and operating_cashflow_change is not None
        and operating_cashflow_change < 0
    ):
        return "利润与经营现金流双重承压"
    if net_profit_change is not None and net_profit_change < 0:
        return "利润承压，驱动已部分拆解"
    if (
        net_profit_change is not None
        and net_profit_change > 0
        and operating_cashflow_change is not None
        and operating_cashflow_change > 0
    ):
        return "利润与经营现金流共同改善"
    if negative_drivers >= 2:
        return "报表驱动分化，负向科目较多"
    return "报表驱动分化，仍需核对业务原因"


def _fmt(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _signed(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):+.3f}".rstrip("0").rstrip(".")


def _money(value: Any, currency: str) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    unit = "亿美元" if currency == "USD" else "亿元" if currency == "CNY" else currency
    return f"{_signed(float(value) / 100_000_000.0)} {unit}"


def _fingerprint(packet: dict[str, Any]) -> str:
    stable = {
        key: packet.get(key)
        for key in (
            "symbol",
            "method",
            "overall_label",
            "latest_period",
            "comparable_period",
            "profit_bridge",
            "expense_analysis",
            "working_capital_analysis",
            "cashflow_analysis",
            "confirmed_mechanical_drivers",
            "plausible_clues",
            "company_explanations",
            "unresolved_causes",
        )
    }
    filing_document = (packet.get("filing_evidence") or {}).get("document") or {}
    stable["filing_document"] = {
        key: filing_document.get(key)
        for key in ("article_code", "report_period", "content_hash")
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
