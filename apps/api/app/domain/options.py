from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_MULTIPLIER = Decimal("100")
OPTIONS_STRATEGY_VERSION = "csp-v1"
MIXED_RANKING_VERSION = "mixed-v1"
ETF_ALLOWLIST = frozenset({"DIA", "IWM", "QQQ", "SPY"})


class CycleMode(StrEnum):
    STOCKS = "stocks"
    OPTIONS = "options"
    MIXED = "mixed"


class AssetClass(StrEnum):
    STOCK = "stock"
    OPTION = "option"


class OptionFeed(StrEnum):
    OPRA = "opra"
    INDICATIVE = "indicative"


class OptionSignalQuality(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class OptionExitReason(StrEnum):
    CRITICAL_RISK = "critical_risk"
    STOP_LOSS = "stop_loss"
    DTE_21 = "dte_21"
    TAKE_PROFIT = "take_profit"
    NONE = "none"


class OptionGuard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    passed: bool
    reason: str


class OptionsCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: str
    options_approved_level: int | None = None
    options_trading_level: int | None = None
    options_buying_power_available: bool = False
    paper_endpoint_valid: bool
    option_assets_available: bool = False
    contracts_accessible: bool = False
    chains_accessible: bool = False
    snapshots_accessible: bool = False
    feed: OptionFeed | None = None
    checked_at: datetime
    blocking_reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status == "available" and not self.blocking_reasons


class OptionThresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    quote_max_age_seconds: int = Field(default=60, ge=1)
    max_spread_absolute: Decimal = Field(default=Decimal("0.50"), gt=0)
    max_spread_pct: Decimal = Field(default=Decimal("0.15"), gt=0)
    min_volume: int = Field(default=50, ge=0)
    min_open_interest: int = Field(default=100, ge=0)
    min_premium: Decimal = Field(default=Decimal("0.25"), gt=0)
    min_iv_relative_ratio: Decimal = Field(default=Decimal("1.10"), gt=0)
    realized_volatility_window: int = Field(default=20, ge=10, le=252)
    min_underlying_dollar_volume: Decimal = Field(default=Decimal("50000000"), gt=0)
    max_price_drift_pct: Decimal = Field(default=Decimal("0.01"), ge=0)


class OptionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    occ_symbol: str = Field(min_length=15, max_length=32)
    underlying: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    underlying_kind: str
    sector: str
    contract_type: str
    position_intent: str
    contracts: int
    tradable: bool
    optionable: bool
    expiration: date
    strike: Decimal = Field(gt=0)
    delta: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    quote_at: datetime | None
    volume: int | None
    open_interest: int | None
    implied_volatility: Decimal | None
    realized_volatility: Decimal | None
    realized_volatility_window: int
    feed: OptionFeed | None
    underlying_price: Decimal = Field(gt=0)
    underlying_quote_at: datetime | None
    underlying_dollar_volume: Decimal | None
    price_drift_pct: Decimal | None
    company_eligible: bool
    earnings_window_clear: bool
    options_market_open: bool
    duplicate_order: bool = False
    duplicate_thesis: bool = False
    incompatible_position: bool = False
    overlapping_close: bool = False
    provider: str = "alpaca"
    observed_at: datetime

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> OptionCandidate:
        for value in (self.quote_at, self.underlying_quote_at, self.observed_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Option timestamps must include a timezone")
        return self


class OptionPortfolio(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    equity: Decimal = Field(gt=0)
    cash: Decimal = Field(ge=0)
    options_buying_power: Decimal = Field(ge=0)
    current_position_assignment_exposure: Decimal = Field(ge=0)
    current_sector_assignment_exposure: Decimal = Field(ge=0)
    sector_company_count: int = Field(ge=0)
    existing_collateral_reservations: Decimal = Field(default=Decimal("0"), ge=0)


class OptionEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy_version: str = OPTIONS_STRATEGY_VERSION
    candidate: OptionCandidate
    collateral: Decimal
    midpoint: Decimal | None
    spread_absolute: Decimal | None
    spread_pct: Decimal | None
    iv_relative_ratio: Decimal | None
    iv_signal_quality: OptionSignalQuality
    eligible: bool
    score: Decimal | None
    guards: tuple[OptionGuard, ...]
    rejected_reasons: tuple[str, ...]


class RankedOpportunity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    asset_class: AssetClass
    identifier: str
    eligible: bool
    safety_margin: Decimal = Field(ge=0, le=1)
    fundamental_quality: Decimal = Field(ge=0, le=1)
    data_quality: Decimal = Field(ge=0, le=1)
    liquidity_quality: Decimal = Field(ge=0, le=1)
    risk_adjusted_return: Decimal = Field(ge=0, le=1)
    concentration_quality: Decimal = Field(ge=0, le=1)
    yellow_penalty: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class MixedSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ranking_version: str = MIXED_RANKING_VERSION
    selected_asset_class: AssetClass | None
    selected_identifier: str | None
    stock_score: Decimal | None
    option_score: Decimal | None
    decision: str


def option_collateral(strike: Decimal, contracts: int) -> Decimal:
    if contracts != 1:
        raise ValueError("Cash-Secured Put entries require exactly one contract")
    if strike <= 0 or not strike.is_finite():
        raise ValueError("Strike must be a positive finite Decimal")
    return (strike * CONTRACT_MULTIPLIER).quantize(Decimal("0.01"))


def realized_volatility(closes: Sequence[Decimal], window: int = 20) -> Decimal | None:
    if window < 2 or len(closes) < window + 1:
        return None
    sample = tuple(closes[-(window + 1) :])
    if any(not item.is_finite() or item <= 0 for item in sample):
        return None
    returns = tuple((right / left) - Decimal("1") for left, right in pairwise(sample))
    mean = sum(returns, Decimal("0")) / Decimal(window)
    variance = sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(window - 1)
    try:
        return (variance * Decimal("252")).sqrt()
    except InvalidOperation:
        return None


def _guard(code: str, passed: bool, reason: str | None = None) -> OptionGuard:
    return OptionGuard(code=code, passed=passed, reason="passed" if passed else reason or code)


def evaluate_option_candidate(
    candidate: OptionCandidate,
    portfolio: OptionPortfolio,
    capability: OptionsCapability,
    mode: CycleMode,
    now: datetime,
    thresholds: OptionThresholds | None = None,
) -> OptionEvaluation:
    limits = thresholds or OptionThresholds()
    instant = now.astimezone(UTC)
    collateral = (candidate.strike * CONTRACT_MULTIPLIER * Decimal(candidate.contracts)).quantize(
        Decimal("0.01")
    )
    dte = (candidate.expiration - instant.date()).days
    midpoint = (
        (candidate.bid + candidate.ask) / Decimal("2")
        if candidate.bid is not None and candidate.ask is not None
        else None
    )
    spread = (
        candidate.ask - candidate.bid
        if candidate.bid is not None and candidate.ask is not None
        else None
    )
    spread_pct = (
        spread / midpoint if spread is not None and midpoint is not None and midpoint > 0 else None
    )
    iv_ratio = (
        candidate.implied_volatility / candidate.realized_volatility
        if candidate.implied_volatility is not None
        and candidate.realized_volatility is not None
        and candidate.realized_volatility > 0
        else None
    )
    quote_fresh = (
        candidate.quote_at is not None
        and Decimal(str((instant - candidate.quote_at.astimezone(UTC)).total_seconds()))
        <= Decimal(limits.quote_max_age_seconds)
        and candidate.quote_at <= instant
    )
    underlying_fresh = (
        candidate.underlying_quote_at is not None
        and Decimal(str((instant - candidate.underlying_quote_at.astimezone(UTC)).total_seconds()))
        <= Decimal(limits.quote_max_age_seconds)
        and candidate.underlying_quote_at <= instant
    )
    remaining_cash = portfolio.cash - portfolio.existing_collateral_reservations - collateral
    assignment_position = portfolio.current_position_assignment_exposure + collateral
    assignment_sector = portfolio.current_sector_assignment_exposure + collateral
    is_etf = candidate.underlying_kind == "etf"
    universe_ok = (
        candidate.tradable
        and candidate.optionable
        and (candidate.underlying in ETF_ALLOWLIST if is_etf else candidate.company_eligible)
    )
    checks = (
        _guard("paper_options_capability", capability.eligible, "options_level_1_required"),
        _guard("options_market_open", candidate.options_market_open),
        _guard("put_only", candidate.contract_type == "put", "calls_are_forbidden"),
        _guard(
            "sell_to_open_only",
            candidate.position_intent == "sell_to_open",
            "entry_must_be_sell_to_open",
        ),
        _guard("one_contract", candidate.contracts == 1, "exactly_one_contract_required"),
        _guard("tradable_universe", universe_ok, "underlying_or_contract_not_eligible"),
        _guard("otm", candidate.strike < candidate.underlying_price, "put_must_be_otm"),
        _guard("dte_30_45", 30 <= dte <= 45, "dte_outside_30_45"),
        _guard(
            "delta_range",
            candidate.delta is not None and Decimal("-0.30") <= candidate.delta <= Decimal("-0.15"),
            "delta_unavailable_or_outside_range",
        ),
        _guard(
            "valid_quote",
            candidate.bid is not None
            and candidate.ask is not None
            and candidate.bid > 0
            and candidate.ask >= candidate.bid
            and midpoint is not None
            and midpoint > 0,
            "invalid_bid_ask_or_midpoint",
        ),
        _guard("quote_fresh", quote_fresh, "option_quote_stale_or_missing"),
        _guard(
            "spread",
            spread is not None
            and spread_pct is not None
            and spread <= limits.max_spread_absolute
            and spread_pct <= limits.max_spread_pct,
            "option_spread_too_wide",
        ),
        _guard(
            "volume",
            candidate.volume is not None and candidate.volume >= limits.min_volume,
            "option_volume_insufficient",
        ),
        _guard(
            "open_interest",
            candidate.open_interest is not None
            and candidate.open_interest >= limits.min_open_interest,
            "option_open_interest_insufficient",
        ),
        _guard(
            "minimum_premium",
            midpoint is not None and midpoint >= limits.min_premium,
            "option_premium_insufficient",
        ),
        _guard(
            "iv_relative_signal",
            iv_ratio is not None and iv_ratio >= limits.min_iv_relative_ratio,
            "iv_relative_signal_unavailable_or_insufficient",
        ),
        _guard(
            "underlying_data",
            underlying_fresh
            and candidate.underlying_dollar_volume is not None
            and candidate.underlying_dollar_volume >= limits.min_underlying_dollar_volume,
            "underlying_data_stale_or_illiquid",
        ),
        _guard(
            "price_drift",
            candidate.price_drift_pct is not None
            and candidate.price_drift_pct <= limits.max_price_drift_pct,
            "underlying_price_drift_exceeded",
        ),
        _guard("earnings_window", candidate.earnings_window_clear),
        _guard("identified_feed", candidate.feed is not None, "options_feed_unavailable"),
        _guard(
            "options_buying_power",
            portfolio.options_buying_power >= collateral,
            "options_buying_power_insufficient",
        ),
        _guard("cash_collateral", remaining_cash >= 0, "full_cash_collateral_unavailable"),
        _guard(
            "minimum_cash",
            remaining_cash / portfolio.equity >= Decimal("0.20"),
            "post_trade_cash_below_20_percent",
        ),
        _guard(
            "assignment_position_cap",
            assignment_position / portfolio.equity <= Decimal("0.10"),
            "assignment_exposure_above_10_percent",
        ),
        _guard(
            "assignment_sector_cap",
            assignment_sector / portfolio.equity <= Decimal("0.20"),
            "assignment_sector_exposure_above_20_percent",
        ),
        _guard(
            "sector_company_cap",
            portfolio.sector_company_count < 2,
            "sector_company_limit_reached",
        ),
        _guard(
            "no_duplicate",
            not candidate.duplicate_order and not candidate.duplicate_thesis,
            "duplicate_order_or_thesis",
        ),
        _guard(
            "compatible_position",
            not candidate.incompatible_position and not candidate.overlapping_close,
            "incompatible_position_or_closing_order",
        ),
        _guard(
            "mixed_underlying_price",
            mode != CycleMode.MIXED or candidate.underlying_price <= Decimal("40"),
            "mixed_options_underlying_above_40",
        ),
    )
    rejected = tuple(item.reason for item in checks if not item.passed)
    score = None
    if (
        not rejected
        and midpoint is not None
        and spread_pct is not None
        and iv_ratio is not None
        and candidate.delta is not None
    ):
        delta_quality = Decimal("1") - abs(candidate.delta - Decimal("-0.22")) / Decimal("0.08")
        liquidity = min(Decimal("1"), Decimal(candidate.open_interest or 0) / Decimal("1000"))
        spread_quality = max(Decimal("0"), Decimal("1") - spread_pct / limits.max_spread_pct)
        capital_quality = max(Decimal("0"), Decimal("1") - collateral / portfolio.equity)
        iv_quality = min(Decimal("1"), iv_ratio / (limits.min_iv_relative_ratio * Decimal("2")))
        score = (
            delta_quality * Decimal("0.20")
            + liquidity * Decimal("0.20")
            + spread_quality * Decimal("0.20")
            + capital_quality * Decimal("0.20")
            + iv_quality * Decimal("0.20")
        ).quantize(Decimal("0.000001"))
    return OptionEvaluation(
        candidate=candidate,
        collateral=collateral,
        midpoint=midpoint,
        spread_absolute=spread,
        spread_pct=spread_pct,
        iv_relative_ratio=iv_ratio,
        iv_signal_quality=(
            OptionSignalQuality.AVAILABLE
            if iv_ratio is not None
            else OptionSignalQuality.UNAVAILABLE
        ),
        eligible=not rejected,
        score=score,
        guards=checks,
        rejected_reasons=rejected,
    )


def rank_option_contracts(evaluations: Sequence[OptionEvaluation]) -> OptionEvaluation | None:
    eligible = [item for item in evaluations if item.eligible and item.score is not None]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item.score or Decimal("0"),
            -item.candidate.strike,
            item.candidate.expiration.toordinal(),
            item.candidate.occ_symbol,
        ),
    )


def opportunity_score(value: RankedOpportunity) -> Decimal | None:
    if not value.eligible:
        return None
    score = (
        value.safety_margin * Decimal("0.20")
        + value.fundamental_quality * Decimal("0.20")
        + value.data_quality * Decimal("0.15")
        + value.liquidity_quality * Decimal("0.15")
        + value.risk_adjusted_return * Decimal("0.15")
        + value.concentration_quality * Decimal("0.15")
        - value.yellow_penalty * Decimal("0.10")
    )
    return max(Decimal("0"), score).quantize(Decimal("0.000001"))


def select_mixed_opportunity(
    stock: RankedOpportunity | None, option: RankedOpportunity | None
) -> MixedSelection:
    stock_score = opportunity_score(stock) if stock is not None else None
    option_score = opportunity_score(option) if option is not None else None
    candidates = [
        (stock_score, AssetClass.STOCK, stock.identifier)
        if stock and stock_score is not None
        else None,
        (option_score, AssetClass.OPTION, option.identifier)
        if option and option_score is not None
        else None,
    ]
    valid = [item for item in candidates if item is not None]
    if not valid:
        return MixedSelection(
            selected_asset_class=None,
            selected_identifier=None,
            stock_score=stock_score,
            option_score=option_score,
            decision="no_trade_no_comparable_eligible_candidate",
        )
    winner = max(valid, key=lambda item: (item[0], item[1] == AssetClass.STOCK, item[2]))
    return MixedSelection(
        selected_asset_class=winner[1],
        selected_identifier=winner[2],
        stock_score=stock_score,
        option_score=option_score,
        decision=f"{winner[1].value}_won_{MIXED_RANKING_VERSION}",
    )


def option_exit_reason(
    *,
    entry_credit: Decimal,
    buyback_price: Decimal,
    dte: int,
    critical_deterioration: bool = False,
    account_risk: bool = False,
) -> OptionExitReason:
    if critical_deterioration or account_risk:
        return OptionExitReason.CRITICAL_RISK
    if buyback_price >= entry_credit * Decimal("3"):
        return OptionExitReason.STOP_LOSS
    if dte <= 21:
        return OptionExitReason.DTE_21
    if buyback_price <= entry_credit * Decimal("0.50"):
        return OptionExitReason.TAKE_PROFIT
    return OptionExitReason.NONE
