from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.fundamentals import (
    equity_criterion,
    free_cash_flow_criterion,
    profitability_criterion,
)
from app.domain.models import (
    Company,
    Confidence,
    FinancialYear,
    FiscalPeriod,
    ProviderBudget,
    RatioCluster,
    RatioObservation,
    Sector,
    TrafficLight,
    UniverseAsset,
    ValuationStatus,
)
from app.domain.universe import evaluate_asset
from app.domain.valuation import build_valuation_range, select_coherent_cluster, valuation_criterion


def year(
    fiscal_year: int,
    *,
    revenue: str = "100",
    income: str = "10",
    ocf: str = "20",
    capex: str = "5",
    assets: str = "100",
    liabilities: str = "50",
) -> FinancialYear:
    return FinancialYear(
        period=FiscalPeriod(
            fiscal_year=fiscal_year, fiscal_period="FY", end=date(fiscal_year, 12, 31)
        ),
        revenue=Decimal(revenue),
        net_income=Decimal(income),
        operating_cash_flow=Decimal(ocf),
        capital_expenditures=Decimal(capex),
        total_assets=Decimal(assets),
        total_liabilities=Decimal(liabilities),
        total_debt=Decimal("10"),
    )


def cluster(kind: str, count: int, value: str = "20") -> RatioCluster:
    return select_coherent_cluster(
        kind,
        [
            RatioObservation(
                ratio_type=kind,
                period_end=date(2024 + index // 4, (index % 4 + 1) * 3, 28),
                value=Decimal(value),
                source_url="https://example.test",
            )
            for index in range(count)
        ],
    )


def test_yellow_fundamental_branches_remain_acceptable() -> None:
    profitability = [
        year(2022, revenue="100", income="20"),
        year(2023, revenue="110", income="21"),
        year(2024, revenue="120", income="22"),
        year(2025, revenue="200", income="23"),
    ]
    assert profitability_criterion(profitability).status == TrafficLight.YELLOW

    fcf = [year(2022, ocf="50"), year(2023, ocf="40"), year(2024, ocf="30"), year(2025, ocf="20")]
    assert free_cash_flow_criterion(fcf).status == TrafficLight.YELLOW

    recovered_equity = [
        year(2022, assets="100"),
        year(2023, assets="120"),
        year(2024, assets="105"),
        year(2025, assets="130"),
    ]
    assert equity_criterion(recovered_equity).status == TrafficLight.YELLOW


def test_every_universe_missing_or_excluded_input_fails_closed() -> None:
    company = Company(
        ticker="FAIL", name="Fixture", exchange="OTC", sector=Sector(slug="finance", name="Finance")
    )
    decision = evaluate_asset(
        UniverseAsset(
            company=company,
            tradable=False,
            us_listed=False,
            instrument_type="crypto",
            market_cap=None,
            average_daily_dollar_volume=None,
            latest_net_income=None,
            current_price=None,
            excluded_industry="insurer",
        )
    )
    assert len(decision.reasons) == 8


def test_valuation_traffic_light_adapter_and_budget_remaining() -> None:
    medium_pe = cluster("pe", 4, "20")
    medium_pfcf = cluster("pfcf", 4, "24")
    green = build_valuation_range(
        Decimal("94"), Decimal("18.8"), Decimal("22.56"), medium_pe, medium_pfcf
    )
    yellow = build_valuation_range(
        Decimal("98"), Decimal("19.6"), Decimal("23.52"), medium_pe, medium_pfcf
    )
    assert green.status == ValuationStatus.GREEN
    assert valuation_criterion(green).status == TrafficLight.GREEN
    assert valuation_criterion(yellow).status == TrafficLight.YELLOW
    insufficient = build_valuation_range(Decimal("1"), None, None, medium_pe, medium_pfcf)
    assert valuation_criterion(insufficient).status == TrafficLight.INSUFFICIENT
    red = green.model_copy(update={"status": ValuationStatus.RED})
    assert valuation_criterion(red).status == TrafficLight.RED
    assert (
        ProviderBudget(
            provider="alpha_vantage", budget_date=date(2026, 9, 2), request_count=3
        ).remaining
        == 22
    )
    assert medium_pe.confidence == Confidence.MEDIUM
