from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.domain.fundamentals import evaluate_fundamentals
from app.domain.models import (
    Company,
    CompanyThesis,
    Eligibility,
    Evidence,
    FinancialYear,
    FiscalPeriod,
    ForwardEstimates,
    MarketContext,
    ProviderProvenance,
    RatioObservation,
    Sector,
    TrafficLight,
)
from app.domain.valuation import build_valuation_range, select_coherent_cluster, valuation_criterion
from app.repositories.analysis import AnalysisRepository


class AnalysisService:
    def __init__(self, repository: AnalysisRepository) -> None:
        self.repository = repository

    async def analyze_fixture(self, owner_id: str, symbol: str, now: datetime) -> CompanyThesis:
        thesis = build_fixture_thesis(symbol, now)
        await self.repository.save_thesis(owner_id, thesis)
        return thesis


def build_fixture_thesis(symbol: str = "AAPL", now: datetime | None = None) -> CompanyThesis:
    generated = now or datetime(2026, 9, 2, 18, 0, tzinfo=UTC)
    sector = Sector(slug="technology", name="Technology")
    company = Company(
        ticker=symbol.upper(),
        name="Fixture Quality Corp.",
        exchange="NASDAQ",
        sector=sector,
        cik="0000320193",
    )
    amounts = (
        (2022, "1000", "110", "180", "50", "1600", "900", "300"),
        (2023, "1120", "126", "195", "52", "1750", "940", "320"),
        (2024, "1240", "145", "215", "55", "1900", "980", "330"),
        (2025, "1390", "168", "240", "58", "2070", "1010", "340"),
    )
    years = tuple(
        FinancialYear(
            period=FiscalPeriod(fiscal_year=row[0], fiscal_period="FY", end=date(row[0], 9, 30)),
            revenue=Decimal(row[1]),
            net_income=Decimal(row[2]),
            operating_cash_flow=Decimal(row[3]),
            capital_expenditures=Decimal(row[4]),
            total_assets=Decimal(row[5]),
            total_liabilities=Decimal(row[6]),
            total_debt=Decimal(row[7]),
        )
        for row in amounts
    )
    alpha = ProviderProvenance.fixture(
        "alpha_vantage", "https://www.alphavantage.co/documentation/#earnings-estimates"
    )
    estimates = ForwardEstimates(
        comparable_period="2026-12-31",
        consensus_eps=Decimal("2.10"),
        previous_consensus_eps=Decimal("2.00"),
        prior_year_eps=Decimal("1.85"),
        provenance=alpha,
    )
    source = "https://www.sec.gov/edgar/browse/?CIK=0000320193"
    pe_values = ("20", "21", "22", "23", "24", "25", "26", "48")
    pfcf_values = ("18", "19", "20", "21", "22", "23", "24", "45")
    pe = select_coherent_cluster(
        "pe",
        tuple(
            RatioObservation(
                ratio_type="pe",
                period_end=date(2024 + index // 4, (index % 4 + 1) * 3, 28),
                value=Decimal(value),
                source_url=source,
            )
            for index, value in enumerate(pe_values)
        ),
    )
    pfcf = select_coherent_cluster(
        "pfcf",
        tuple(
            RatioObservation(
                ratio_type="pfcf",
                period_end=date(2024 + index // 4, (index % 4 + 1) * 3, 28),
                value=Decimal(value),
                source_url=source,
            )
            for index, value in enumerate(pfcf_values)
        ),
    )
    valuation = build_valuation_range(Decimal("140"), Decimal("28"), Decimal("26"), pe, pfcf)
    valuation = valuation.model_copy(
        update={
            "report_date": date(2026, 7, 30),
            "frozen_at": generated,
            "refresh_eligible_at": generated,
        }
    )
    raw_criteria = (*evaluate_fundamentals(years, estimates), valuation_criterion(valuation))
    criteria = tuple(
        item.model_copy(
            update={
                "evidence_ids": (
                    ("alpha-fixture-estimates",)
                    if item.criterion == "forward_estimates"
                    else (
                        ("sec-fixture-annual", "alpaca-fixture-market")
                        if item.criterion == "self_relative_valuation"
                        else ("sec-fixture-annual",)
                    )
                )
            }
        )
        for item in raw_criteria
    )
    reasons = tuple(
        f"{result.criterion}:{result.status.value}"
        for result in criteria
        if result.status in (TrafficLight.RED, TrafficLight.INSUFFICIENT)
    )
    evidence = (
        Evidence(
            evidence_id="sec-fixture-annual",
            title="Sanitized SEC annual facts fixture",
            provenance=ProviderProvenance.fixture("sec_edgar", source),
        ),
        Evidence(
            evidence_id="alpha-fixture-estimates",
            title="Sanitized Alpha Vantage estimate fixture",
            provenance=alpha,
        ),
        Evidence(
            evidence_id="alpaca-fixture-market",
            title="Sanitized Alpaca market fixture",
            provenance=ProviderProvenance.fixture(
                "alpaca", "https://docs.alpaca.markets/docs/market-data"
            ),
        ),
    )
    return CompanyThesis(
        company=company,
        generated_at=generated,
        eligibility=Eligibility.NO_TRADE if reasons else Eligibility.ELIGIBLE,
        criteria=criteria,
        pe_cluster=pe,
        pfcf_cluster=pfcf,
        valuation=valuation,
        evidence=evidence,
        no_trade_reasons=reasons,
        fresh_until=generated + timedelta(hours=24),
        earnings_state="open",
        financial_years=years,
        forward_estimates=estimates,
        market=MarketContext(
            price=valuation.current_price,
            bid=Decimal("139.90"),
            ask=Decimal("140.10"),
            average_daily_dollar_volume=Decimal("50000000"),
            observed_at=generated,
            provenance=evidence[2].provenance,
        ),
    )
