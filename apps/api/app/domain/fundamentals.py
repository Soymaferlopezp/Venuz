from __future__ import annotations

import itertools
from collections.abc import Sequence
from decimal import Decimal

from app.domain.models import CriterionResult, FinancialYear, ForwardEstimates, TrafficLight


def _ordered_years(years: Sequence[FinancialYear]) -> list[FinancialYear]:
    return sorted(years, key=lambda item: item.period.end)[-4:]


def _insufficient(name: str, formula: str, reason: str) -> CriterionResult:
    return CriterionResult(
        criterion=name,
        status=TrafficLight.INSUFFICIENT,
        formula=formula,
        reason=reason,
        values={},
    )


def revenue_criterion(years: Sequence[FinancialYear]) -> CriterionResult:
    ordered = _ordered_years(years)
    formula = "latest revenue > first revenue; assess each year-over-year comparison"
    if len(ordered) < 4:
        return _insufficient("revenue_trend", formula, "Four fiscal years are required")
    values = [year.revenue for year in ordered]
    positive_steps = sum(right > left for left, right in itertools.pairwise(values))
    recovered = values[-1] > values[-2]
    if values[-1] <= values[0]:
        status = TrafficLight.RED
        reason = "Revenue did not grow from the first to latest fiscal year"
    elif positive_steps == 3:
        status = TrafficLight.GREEN
        reason = "Revenue grew in every available year-over-year comparison"
    elif positive_steps == 2 and recovered:
        status = TrafficLight.YELLOW
        reason = "One isolated decline was followed by recovery"
    else:
        status = TrafficLight.RED
        reason = "Revenue trend has repeated or unrecovered declines"
    return CriterionResult(
        criterion="revenue_trend",
        status=status,
        formula=formula,
        reason=reason,
        values={"first": values[0], "latest": values[-1], "positive_steps": positive_steps},
    )


def profitability_criterion(years: Sequence[FinancialYear]) -> CriterionResult:
    ordered = _ordered_years(years)
    formula = "net margin = net income / revenue; latest net income and margin > 0"
    if len(ordered) < 4 or any(year.net_margin is None for year in ordered):
        return _insufficient("profitability", formula, "Four valid revenue periods are required")
    latest = ordered[-1]
    margins = [year.net_margin for year in ordered]
    assert all(margin is not None for margin in margins)
    concrete_margins = [margin for margin in margins if margin is not None]
    if latest.net_income <= 0 or concrete_margins[-1] <= 0:
        status = TrafficLight.RED
        reason = "Latest net income or net margin is not positive"
    elif latest.net_income > ordered[0].net_income and concrete_margins[-1] >= concrete_margins[0]:
        status = TrafficLight.GREEN
        reason = "Net income grew overall and net margin is stable or higher"
    else:
        status = TrafficLight.YELLOW
        reason = "Profitable, but income or margin quality has an isolated weakness"
    return CriterionResult(
        criterion="profitability",
        status=status,
        formula=formula,
        reason=reason,
        values={"latest_net_income": latest.net_income, "latest_net_margin": concrete_margins[-1]},
    )


def free_cash_flow_criterion(years: Sequence[FinancialYear]) -> CriterionResult:
    ordered = _ordered_years(years)
    formula = "FCF = operating cash flow - capital expenditures; positive >= 3/4 and latest > 0"
    if len(ordered) < 4:
        return _insufficient("free_cash_flow", formula, "Four fiscal years are required")
    values = [year.free_cash_flow for year in ordered]
    positive_count = sum(value > 0 for value in values)
    if values[-1] <= 0 or positive_count < 3:
        status = TrafficLight.RED
        reason = "Latest FCF is not positive or fewer than three years are positive"
    elif values[-1] >= values[0]:
        status = TrafficLight.GREEN
        reason = "FCF passes 3-of-4 and is stable or growing overall"
    else:
        status = TrafficLight.YELLOW
        reason = "FCF passes required positives but declined overall"
    return CriterionResult(
        criterion="free_cash_flow",
        status=status,
        formula=formula,
        reason=reason,
        values={"latest": values[-1], "positive_years": positive_count},
    )


def equity_criterion(years: Sequence[FinancialYear]) -> CriterionResult:
    ordered = _ordered_years(years)
    formula = "shareholders' equity = total assets - total liabilities; latest > 0"
    if len(ordered) < 4:
        return _insufficient("shareholders_equity", formula, "Four fiscal years are required")
    values = [year.shareholders_equity for year in ordered]
    positive_steps = sum(right >= left for left, right in itertools.pairwise(values))
    if values[-1] <= 0:
        status = TrafficLight.RED
        reason = "Latest shareholders' equity is not positive"
    elif positive_steps == 3:
        status = TrafficLight.GREEN
        reason = "Shareholders' equity is positive and non-declining"
    elif values[-1] >= values[0] and values[-1] > values[-2]:
        status = TrafficLight.YELLOW
        reason = "An isolated decline was followed by recovery"
    else:
        status = TrafficLight.YELLOW
        reason = "Equity is positive but its four-year trend is weaker"
    return CriterionResult(
        criterion="shareholders_equity",
        status=status,
        formula=formula,
        reason=reason,
        values={"latest": values[-1], "non_declining_steps": positive_steps},
    )


def debt_equity_criterion(years: Sequence[FinancialYear]) -> CriterionResult:
    ordered = _ordered_years(years)
    formula = "Debt/Equity = total debt / (total assets - total liabilities); ratio < 1"
    if len(ordered) < 4:
        return _insufficient("debt_equity", formula, "Four fiscal years are required")
    latest = ordered[-1]
    equity = latest.shareholders_equity
    if equity <= 0:
        return CriterionResult(
            criterion="debt_equity",
            status=TrafficLight.RED,
            formula=formula,
            reason="Debt/Equity is invalid because latest equity is not positive",
            values={"latest_equity": equity},
        )
    ratio = latest.total_debt / equity
    return CriterionResult(
        criterion="debt_equity",
        status=TrafficLight.GREEN if ratio < Decimal("1") else TrafficLight.RED,
        formula=formula,
        reason="Debt/Equity is below 1" if ratio < 1 else "Debt/Equity is 1 or higher",
        values={"ratio": ratio},
    )


def forward_estimates_criterion(estimates: ForwardEstimates | None) -> CriterionResult:
    formula = "consensus EPS > previous consensus AND expected EPS > comparable prior-year EPS"
    if estimates is None or None in (
        estimates.consensus_eps,
        estimates.previous_consensus_eps,
        estimates.prior_year_eps,
    ):
        return _insufficient("forward_estimates", formula, "Both estimate signals are required")
    current = estimates.consensus_eps
    previous = estimates.previous_consensus_eps
    prior_year = estimates.prior_year_eps
    assert current is not None and previous is not None and prior_year is not None
    revision_up = current > previous
    growth_up = current > prior_year
    passed = revision_up and growth_up
    return CriterionResult(
        criterion="forward_estimates",
        status=TrafficLight.GREEN if passed else TrafficLight.RED,
        formula=formula,
        reason="Both forward signals are positive"
        if passed
        else "One or both forward signals failed",
        values={"revision_up": revision_up, "expected_growth_up": growth_up},
    )


def evaluate_fundamentals(
    years: Sequence[FinancialYear], estimates: ForwardEstimates | None
) -> tuple[CriterionResult, ...]:
    return (
        revenue_criterion(years),
        profitability_criterion(years),
        free_cash_flow_criterion(years),
        equity_criterion(years),
        debt_equity_criterion(years),
        forward_estimates_criterion(estimates),
    )
