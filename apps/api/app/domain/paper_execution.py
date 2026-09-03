from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CycleState(StrEnum):
    QUEUED = "queued"
    EXPLORING = "exploring"
    ANALYZING = "analyzing"
    EVALUATING_TRADE = "evaluating_trade"
    PAPER_ORDER_SUBMITTED = "paper_order_submitted"
    MONITORING = "monitoring"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    QUOTA_EXHAUSTED = "quota_exhausted"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    FAILED_SAFE = "failed_safe"


ALLOWED_TRANSITIONS: dict[CycleState, set[CycleState]] = {
    CycleState.QUEUED: {CycleState.EXPLORING, CycleState.FAILED_SAFE},
    CycleState.EXPLORING: {
        CycleState.ANALYZING,
        CycleState.QUOTA_EXHAUSTED,
        CycleState.PROVIDER_UNAVAILABLE,
        CycleState.FAILED_SAFE,
    },
    CycleState.ANALYZING: {
        CycleState.EVALUATING_TRADE,
        CycleState.QUOTA_EXHAUSTED,
        CycleState.PROVIDER_UNAVAILABLE,
        CycleState.FAILED_SAFE,
    },
    CycleState.EVALUATING_TRADE: {
        CycleState.PAPER_ORDER_SUBMITTED,
        CycleState.BLOCKED,
        CycleState.COMPLETED,
        CycleState.FAILED_SAFE,
    },
    CycleState.PAPER_ORDER_SUBMITTED: {CycleState.MONITORING, CycleState.FAILED_SAFE},
    CycleState.MONITORING: {CycleState.COMPLETED, CycleState.BLOCKED, CycleState.FAILED_SAFE},
}


class InvalidTransition(ValueError):
    pass


def assert_transition(current: CycleState, target: CycleState) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"Invalid cycle transition: {current} -> {target}")


def cycle_key(strategy_version: str, market_session: date, data_cutoff: datetime) -> str:
    cutoff = data_cutoff.astimezone(UTC).replace(microsecond=0).isoformat()
    return f"{strategy_version}:{market_session.isoformat()}:{cutoff}"


class GuardResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    passed: bool
    reason: str


class PreflightInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    market_open: bool
    regular_session: bool
    data_fresh: bool
    data_coherent: bool
    company_eligible: bool
    criteria_passed: bool
    valuation_eligible: bool
    outside_earnings_block: bool
    quote_fresh: bool
    spread_pct: Decimal = Field(ge=0)
    max_spread_pct: Decimal = Field(default=Decimal("0.005"), ge=0)
    price_drift_pct: Decimal = Field(ge=0)
    max_price_drift_pct: Decimal = Field(default=Decimal("0.01"), ge=0)
    buying_power: Decimal = Field(ge=0)
    order_notional: Decimal = Field(gt=0)
    portfolio_equity: Decimal = Field(gt=0)
    cash: Decimal = Field(ge=0)
    current_position_value: Decimal = Field(ge=0)
    current_sector_value: Decimal = Field(ge=0)
    sector_company_count: int = Field(ge=0)
    duplicate_order: bool = False
    duplicate_thesis: bool = False


class PreflightDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    eligible: bool
    guards: tuple[GuardResult, ...]


def evaluate_preflight(value: PreflightInput) -> PreflightDecision:
    checks = (
        ("regular_market_open", value.market_open and value.regular_session),
        ("data_sufficient", value.data_fresh and value.data_coherent),
        ("company_eligible", value.company_eligible),
        ("criteria_passed", value.criteria_passed),
        ("valuation_margin", value.valuation_eligible),
        ("earnings_window", value.outside_earnings_block),
        ("liquidity_and_spread", value.quote_fresh and value.spread_pct <= value.max_spread_pct),
        ("price_drift", value.price_drift_pct <= value.max_price_drift_pct),
        ("buying_power", value.buying_power >= value.order_notional),
        (
            "minimum_cash",
            (value.cash - value.order_notional) / value.portfolio_equity >= Decimal("0.20"),
        ),
        (
            "position_cap",
            (value.current_position_value + value.order_notional) / value.portfolio_equity
            <= Decimal("0.10"),
        ),
        (
            "sector_cap",
            (value.current_sector_value + value.order_notional) / value.portfolio_equity
            <= Decimal("0.20"),
        ),
        ("sector_company_cap", value.sector_company_count < 2),
        ("no_duplicate", not value.duplicate_order and not value.duplicate_thesis),
    )
    guards = tuple(
        GuardResult(code=code, passed=passed, reason="passed" if passed else f"{code}_blocked")
        for code, passed in checks
    )
    return PreflightDecision(eligible=all(item.passed for item in guards), guards=guards)


def protection_prices(fill_price: Decimal) -> tuple[Decimal, Decimal]:
    stop = (fill_price * Decimal("0.90")).quantize(Decimal("0.01"))
    objective = (fill_price + (fill_price - stop) * 2).quantize(Decimal("0.01"))
    return stop, objective
