from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.calendar import EarningsState, earnings_state, should_recalculate
from app.domain.fundamentals import (
    debt_equity_criterion,
    equity_criterion,
    forward_estimates_criterion,
    free_cash_flow_criterion,
    profitability_criterion,
    revenue_criterion,
)
from app.domain.models import (
    Company,
    Confidence,
    Eligibility,
    FinancialYear,
    FiscalPeriod,
    ForwardEstimates,
    ProviderProvenance,
    RatioObservation,
    Sector,
    TrafficLight,
    UniverseAsset,
    ValuationStatus,
)
from app.domain.universe import build_watchlist, evaluate_asset
from app.domain.valuation import build_valuation_range, select_coherent_cluster


def make_year(
    year: int,
    revenue: str,
    net_income: str = "100",
    ocf: str = "180",
    capex: str = "50",
    assets: str = "1000",
    liabilities: str = "500",
    debt: str = "200",
) -> FinancialYear:
    return FinancialYear(
        period=FiscalPeriod(fiscal_year=year, fiscal_period="FY", end=date(year, 12, 31)),
        revenue=Decimal(revenue),
        net_income=Decimal(net_income),
        operating_cash_flow=Decimal(ocf),
        capital_expenditures=Decimal(capex),
        total_assets=Decimal(assets),
        total_liabilities=Decimal(liabilities),
        total_debt=Decimal(debt),
    )


def healthy_years() -> list[FinancialYear]:
    return [
        make_year(2022, "1000", "100", assets="1000", liabilities="600"),
        make_year(2023, "1100", "120", assets="1100", liabilities="620"),
        make_year(2024, "1200", "145", assets="1200", liabilities="640"),
        make_year(2025, "1350", "170", assets="1350", liabilities="660"),
    ]


def observations(kind: str, values: Sequence[str | None]) -> list[RatioObservation]:
    return [
        RatioObservation(
            ratio_type=kind,
            period_end=date(2024 + index // 4, 3 * (index % 4 + 1), 28),
            value=Decimal(value) if value is not None else None,
            source_url="https://example.test/filing",
        )
        for index, value in enumerate(values)
    ]


def test_financial_formulas_and_healthy_criteria() -> None:
    years = healthy_years()
    assert years[-1].free_cash_flow == Decimal("130")
    assert years[-1].shareholders_equity == Decimal("690")
    assert years[-1].net_margin == Decimal("170") / Decimal("1350")
    assert revenue_criterion(years).status == TrafficLight.GREEN
    assert profitability_criterion(years).status == TrafficLight.GREEN
    assert free_cash_flow_criterion(years).status == TrafficLight.GREEN
    assert equity_criterion(years).status == TrafficLight.GREEN
    assert debt_equity_criterion(years).status == TrafficLight.GREEN


def test_missing_periods_and_zero_revenue_are_insufficient() -> None:
    years = healthy_years()[:3]
    assert revenue_criterion(years).status == TrafficLight.INSUFFICIENT
    assert free_cash_flow_criterion(years).status == TrafficLight.INSUFFICIENT
    assert equity_criterion(years).status == TrafficLight.INSUFFICIENT
    assert debt_equity_criterion(years).status == TrafficLight.INSUFFICIENT
    zero = healthy_years()
    zero[-1] = make_year(2025, "0")
    assert profitability_criterion(zero).status == TrafficLight.INSUFFICIENT


def test_revenue_single_decline_with_recovery_is_yellow() -> None:
    years = [
        make_year(2022, "100"),
        make_year(2023, "120"),
        make_year(2024, "110"),
        make_year(2025, "140"),
    ]
    assert revenue_criterion(years).status == TrafficLight.YELLOW


def test_revenue_unrecovered_or_no_overall_growth_is_red() -> None:
    assert (
        revenue_criterion(
            [
                make_year(2022, "100"),
                make_year(2023, "130"),
                make_year(2024, "120"),
                make_year(2025, "110"),
            ]
        ).status
        == TrafficLight.RED
    )
    assert (
        revenue_criterion(
            [
                make_year(2022, "100"),
                make_year(2023, "90"),
                make_year(2024, "120"),
                make_year(2025, "110"),
            ]
        ).status
        == TrafficLight.RED
    )


def test_negative_latest_profit_fcf_equity_and_high_debt_are_red() -> None:
    years = healthy_years()
    years[-1] = make_year(
        2025,
        "1350",
        net_income="-1",
        ocf="40",
        capex="50",
        assets="500",
        liabilities="600",
        debt="600",
    )
    assert profitability_criterion(years).status == TrafficLight.RED
    assert free_cash_flow_criterion(years).status == TrafficLight.RED
    assert equity_criterion(years).status == TrafficLight.RED
    assert debt_equity_criterion(years).status == TrafficLight.RED


def test_fcf_requires_three_of_four_and_latest_positive() -> None:
    years = healthy_years()
    years[0] = make_year(2022, "1000", ocf="40", capex="50")
    assert free_cash_flow_criterion(years).status in (TrafficLight.GREEN, TrafficLight.YELLOW)
    years[1] = make_year(2023, "1100", ocf="40", capex="50")
    assert free_cash_flow_criterion(years).status == TrafficLight.RED


def test_forward_signals_require_both_inputs_and_both_passes() -> None:
    provenance = ProviderProvenance.fixture("alpha_vantage", "https://example.test")
    passing = ForwardEstimates(
        comparable_period="Q1",
        consensus_eps=Decimal("2"),
        previous_consensus_eps=Decimal("1.9"),
        prior_year_eps=Decimal("1.8"),
        provenance=provenance,
    )
    failing = passing.model_copy(update={"prior_year_eps": Decimal("2.1")})
    assert forward_estimates_criterion(passing).status == TrafficLight.GREEN
    assert forward_estimates_criterion(failing).status == TrafficLight.RED
    assert forward_estimates_criterion(None).status == TrafficLight.INSUFFICIENT


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["10", "11", "12"], Confidence.LOW),
        (["10", "11", "12", "13"], Confidence.MEDIUM),
        (["10", "11", "12", "13", "14", "15"], Confidence.HIGH),
        (["10", "100"], Confidence.INSUFFICIENT),
    ],
)
def test_cluster_confidence_and_determinism(values: list[str], expected: Confidence) -> None:
    first = select_coherent_cluster("pe", observations("pe", values))
    second = select_coherent_cluster("pe", list(reversed(observations("pe", values))))
    assert first.median == second.median
    assert first.confidence == expected


def test_cluster_even_odd_median_and_exclusion_reasons() -> None:
    odd = select_coherent_cluster("pe", observations("pe", ["10", "11", "12", "90", "0", None]))
    even = select_coherent_cluster("pfcf", observations("pfcf", ["10", "11", "12", "13"]))
    assert odd.median == Decimal("11")
    assert even.median == Decimal("11.5")
    reasons = {item.reason for item in odd.observations if not item.included}
    assert {"outside deterministic 1.50x coherent cluster", "nonpositive", "missing"} <= reasons


def test_valuation_keeps_pe_and_pfcf_separate_and_applies_safety_margin() -> None:
    pe = select_coherent_cluster("pe", observations("pe", ["20", "20", "20", "20"]))
    pfcf = select_coherent_cluster("pfcf", observations("pfcf", ["30", "30", "30", "30"]))
    value = build_valuation_range(Decimal("80"), Decimal("16"), Decimal("20"), pe, pfcf)
    assert value.estimated_price_pe == Decimal("100")
    assert value.estimated_price_pfcf == Decimal("120")
    assert value.floor == Decimal("100") and value.ceiling == Decimal("120")
    assert value.green_price == Decimal("95.00")
    assert value.strong_green_price == Decimal("90.00")
    assert value.status == ValuationStatus.STRONG_GREEN
    assert value.automatic_action_eligible


def test_invalid_current_ratios_are_insufficient_without_dividing_by_zero() -> None:
    cluster = select_coherent_cluster("pe", observations("pe", ["10", "11", "12", "13"]))
    value = build_valuation_range(Decimal("100"), Decimal("0"), None, cluster, cluster)
    assert value.status == ValuationStatus.INSUFFICIENT
    assert not value.automatic_action_eligible


def test_valuation_red_above_ceiling_and_low_confidence_yellow() -> None:
    medium = select_coherent_cluster("pe", observations("pe", ["10", "10", "10", "10"]))
    low = select_coherent_cluster("pfcf", observations("pfcf", ["10", "10", "10"]))
    assert (
        build_valuation_range(Decimal("200"), Decimal("20"), Decimal("20"), medium, medium).status
        == ValuationStatus.RED
    )
    assert (
        build_valuation_range(Decimal("90"), Decimal("10"), Decimal("10"), low, low).status
        == ValuationStatus.YELLOW
    )


def test_earnings_windows_use_sessions_not_calendar_days() -> None:
    sessions = [
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 8),
    ]
    assert (
        earnings_state(date(2026, 9, 2), sessions, date(2026, 9, 1), None)
        == EarningsState.POST_EARNINGS_WAIT
    )
    assert should_recalculate(date(2026, 9, 3), sessions, date(2026, 9, 1), None)
    assert (
        earnings_state(date(2026, 9, 2), sessions, None, date(2026, 9, 8))
        == EarningsState.PRE_EARNINGS_BLOCK
    )
    assert earnings_state(date(2026, 8, 28), sessions, None, date(2026, 9, 8)) == EarningsState.OPEN


def make_asset(index: int, **updates: object) -> UniverseAsset:
    sector = Sector(slug=f"sector-{index % 2}", name=f"Sector {index % 2}")
    asset = UniverseAsset(
        company=Company(
            ticker=f"A{index}", name=f"Company {index}", exchange="NYSE", sector=sector
        ),
        tradable=True,
        us_listed=True,
        instrument_type="equity",
        market_cap=Decimal("20000000000") + index,
        average_daily_dollar_volume=Decimal("30000000"),
        latest_net_income=Decimal("100"),
        current_price=Decimal("10"),
    )
    return asset.model_copy(update=updates)


def test_universe_filters_and_watchlist_bounds() -> None:
    assert evaluate_asset(make_asset(1)).eligibility == Eligibility.ELIGIBLE
    excluded = make_asset(2, excluded_industry="bank", current_price=Decimal("4"))
    assert evaluate_asset(excluded).eligibility == Eligibility.NO_TRADE
    assert len(build_watchlist([make_asset(index) for index in range(20)], size=10)) == 10
    with pytest.raises(ValueError, match="between 10 and 15"):
        build_watchlist([], size=9)


def test_provenance_requires_explicit_timezone() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        ProviderProvenance(
            provider="sec",
            source_url="https://example.test",
            fetched_at=datetime(2026, 1, 1),
            source_as_of=date(2026, 1, 1),
        )
