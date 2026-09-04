from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.options import (
    AssetClass,
    CycleMode,
    OptionCandidate,
    OptionEvaluation,
    OptionFeed,
    OptionPortfolio,
    OptionsCapability,
    RankedOpportunity,
    evaluate_option_candidate,
    option_collateral,
    option_exit_reason,
    rank_option_contracts,
    realized_volatility,
    select_mixed_opportunity,
)

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


def capability(**updates: object) -> OptionsCapability:
    base = OptionsCapability(
        status="available",
        options_approved_level=1,
        options_trading_level=1,
        options_buying_power_available=True,
        paper_endpoint_valid=True,
        option_assets_available=True,
        contracts_accessible=True,
        chains_accessible=True,
        snapshots_accessible=True,
        feed=OptionFeed.INDICATIVE,
        checked_at=NOW,
    )
    return base.model_copy(update=updates)


def portfolio(**updates: object) -> OptionPortfolio:
    base = OptionPortfolio(
        equity=Decimal("100000"),
        cash=Decimal("50000"),
        options_buying_power=Decimal("50000"),
        current_position_assignment_exposure=Decimal("0"),
        current_sector_assignment_exposure=Decimal("0"),
        sector_company_count=0,
    )
    return base.model_copy(update=updates)


def candidate(**updates: object) -> OptionCandidate:
    base = OptionCandidate(
        occ_symbol="AAPL261003P00030000",
        underlying="AAPL",
        underlying_kind="equity",
        sector="Technology",
        contract_type="put",
        position_intent="sell_to_open",
        contracts=1,
        tradable=True,
        optionable=True,
        expiration=date(2026, 10, 3),
        strike=Decimal("30"),
        delta=Decimal("-0.22"),
        bid=Decimal("1.00"),
        ask=Decimal("1.10"),
        quote_at=NOW,
        volume=500,
        open_interest=1000,
        implied_volatility=Decimal("0.30"),
        realized_volatility=Decimal("0.20"),
        realized_volatility_window=20,
        feed=OptionFeed.INDICATIVE,
        underlying_price=Decimal("35"),
        underlying_quote_at=NOW,
        underlying_dollar_volume=Decimal("100000000"),
        price_drift_pct=Decimal("0.001"),
        company_eligible=True,
        earnings_window_clear=True,
        options_market_open=True,
        observed_at=NOW,
    )
    return base.model_copy(update=updates)


def evaluate(
    c: OptionCandidate | None = None,
    p: OptionPortfolio | None = None,
    cap: OptionsCapability | None = None,
    mode: CycleMode = CycleMode.OPTIONS,
) -> OptionEvaluation:
    return evaluate_option_candidate(
        c or candidate(), p or portfolio(), cap or capability(), mode, NOW
    )


def blocked_guard(result: object, code: str) -> bool:
    return any(item.code == code and not item.passed for item in result.guards)  # type: ignore[attr-defined]


def test_valid_candidate_and_decimal_collateral() -> None:
    result = evaluate()
    assert result.eligible and result.score is not None
    assert result.collateral == Decimal("3000.00")
    assert option_collateral(Decimal("30.1234"), 1) == Decimal("3012.34")
    with pytest.raises(ValueError):
        option_collateral(Decimal("30"), 2)


@pytest.mark.parametrize(
    ("updates", "guard"),
    [
        ({"contract_type": "call"}, "put_only"),
        ({"strike": Decimal("35")}, "otm"),
        ({"expiration": date(2026, 10, 2)}, "dte_30_45"),
        ({"expiration": date(2026, 10, 19)}, "dte_30_45"),
        ({"delta": Decimal("-0.31")}, "delta_range"),
        ({"delta": Decimal("-0.14")}, "delta_range"),
        ({"bid": Decimal("0")}, "valid_quote"),
        ({"ask": Decimal("0.90")}, "valid_quote"),
        ({"ask": Decimal("2")}, "spread"),
        ({"quote_at": NOW - timedelta(seconds=61)}, "quote_fresh"),
        ({"implied_volatility": None}, "iv_relative_signal"),
        ({"realized_volatility": Decimal("0")}, "iv_relative_signal"),
        ({"implied_volatility": Decimal("0.20")}, "iv_relative_signal"),
        ({"volume": 49}, "volume"),
        ({"open_interest": 99}, "open_interest"),
        ({"bid": Decimal("0.10"), "ask": Decimal("0.20")}, "minimum_premium"),
        ({"contracts": 2}, "one_contract"),
        ({"earnings_window_clear": False}, "earnings_window"),
        ({"feed": None}, "identified_feed"),
        ({"duplicate_order": True}, "no_duplicate"),
        ({"duplicate_thesis": True}, "no_duplicate"),
        ({"incompatible_position": True}, "compatible_position"),
        ({"overlapping_close": True}, "compatible_position"),
    ],
)
def test_contract_and_data_rejections(updates: dict[str, object], guard: str) -> None:
    assert blocked_guard(evaluate(candidate(**updates)), guard)


@pytest.mark.parametrize("days", [30, 45])
def test_dte_boundaries_approved(days: int) -> None:
    assert evaluate(candidate(expiration=NOW.date() + timedelta(days=days))).eligible


@pytest.mark.parametrize("delta", [Decimal("-0.30"), Decimal("-0.15")])
def test_delta_boundaries_approved(delta: Decimal) -> None:
    assert evaluate(candidate(delta=delta)).eligible


@pytest.mark.parametrize(
    ("updates", "guard"),
    [
        ({"options_buying_power": Decimal("2999")}, "options_buying_power"),
        ({"cash": Decimal("22000")}, "minimum_cash"),
        ({"current_position_assignment_exposure": Decimal("8000")}, "assignment_position_cap"),
        ({"current_sector_assignment_exposure": Decimal("18000")}, "assignment_sector_cap"),
        ({"sector_company_count": 2}, "sector_company_cap"),
    ],
)
def test_portfolio_rejections(updates: dict[str, object], guard: str) -> None:
    assert blocked_guard(evaluate(p=portfolio(**updates)), guard)


def test_level_one_is_required_and_stocks_can_continue() -> None:
    blocked = capability(
        status="blocked",
        options_approved_level=0,
        options_trading_level=0,
        blocking_reasons=("options_approved_level_1_required",),
    )
    assert blocked_guard(evaluate(cap=blocked), "paper_options_capability")
    assert not blocked.eligible


def test_mixed_price_cap_and_etf_allowlist() -> None:
    assert blocked_guard(
        evaluate(candidate(underlying_price=Decimal("40.01")), mode=CycleMode.MIXED),
        "mixed_underlying_price",
    )
    etf = candidate(underlying="SPY", underlying_kind="etf", company_eligible=False)
    assert evaluate(etf).eligible
    assert blocked_guard(
        evaluate(etf.model_copy(update={"underlying": "VTI"})), "tradable_universe"
    )


def test_realized_volatility_and_invalid_series() -> None:
    closes = tuple(Decimal(100 + index) for index in range(21))
    assert realized_volatility(closes, 20) is not None
    assert realized_volatility(closes[:10], 20) is None
    assert realized_volatility((*closes[:-1], Decimal("0")), 20) is None


def opportunity(
    asset: AssetClass, identifier: str, score: str = "0.8", **updates: object
) -> RankedOpportunity:
    base = RankedOpportunity(
        asset_class=asset,
        identifier=identifier,
        eligible=True,
        safety_margin=Decimal(score),
        fundamental_quality=Decimal(score),
        data_quality=Decimal(score),
        liquidity_quality=Decimal(score),
        risk_adjusted_return=Decimal(score),
        concentration_quality=Decimal(score),
    )
    return base.model_copy(update=updates)


def test_mixed_selects_one_deterministically_and_stocks_win_tie() -> None:
    stock = opportunity(AssetClass.STOCK, "AAPL")
    option = opportunity(AssetClass.OPTION, "AAPL261003P00030000", "0.9")
    first = select_mixed_opportunity(stock, option)
    second = select_mixed_opportunity(stock, option)
    assert first == second and first.selected_asset_class == AssetClass.OPTION
    tied = select_mixed_opportunity(stock, opportunity(AssetClass.OPTION, "OPT"))
    assert tied.selected_asset_class == AssetClass.STOCK
    none = select_mixed_opportunity(None, None)
    assert none.selected_asset_class is None


def test_contract_ranking_is_reproducible() -> None:
    first = evaluate()
    second = evaluate(candidate(occ_symbol="AAPL261003P00029000", strike=Decimal("29")))
    assert rank_option_contracts((first, second)) == rank_option_contracts((first, second))
    assert rank_option_contracts((evaluate(candidate(contract_type="call")),)) is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"critical_deterioration": True}, "critical_risk"),
        ({"account_risk": True}, "critical_risk"),
        ({"buyback_price": Decimal("3")}, "stop_loss"),
        ({"buyback_price": Decimal("2.99")}, "none"),
        ({"dte": 21}, "dte_21"),
        ({"buyback_price": Decimal("0.50")}, "take_profit"),
    ],
)
def test_exit_rules_and_priority(kwargs: dict[str, object], expected: str) -> None:
    values = {"entry_credit": Decimal("1"), "buyback_price": Decimal("1"), "dte": 30}
    values.update(kwargs)
    assert option_exit_reason(**values).value == expected  # type: ignore[arg-type]
