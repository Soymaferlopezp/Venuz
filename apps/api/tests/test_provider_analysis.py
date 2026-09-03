from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.domain.models import ForwardEstimates, ProviderProvenance, ValuationStatus
from app.integrations.alpaca import AlpacaReadClient
from app.integrations.alpha_vantage import AlphaVantageClient
from app.integrations.base import ProviderError
from app.integrations.sec import SecEdgarClient
from app.repositories.analysis import MemoryAnalysisRepository
from app.services.provider_analysis import (
    ProviderAnalysisService,
    _repriced,
    build_ratio_inputs,
    latest_report_date,
    normalize_financial_years,
)


def provider_payload() -> dict[str, Any]:
    facts: dict[str, Any] = {}
    annual = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": [1000, 1100, 1200, 1300],
        "NetIncomeLoss": [100, 120, 140, 160],
        "NetCashProvidedByUsedInOperatingActivities": [180, 195, 210, 230],
        "PaymentsToAcquirePropertyPlantAndEquipment": [40, 42, 44, 46],
        "Assets": [1600, 1700, 1800, 1900],
        "Liabilities": [800, 820, 840, 860],
        "LongTermDebtAndFinanceLeaseObligations": [300, 310, 320, 330],
    }
    for concept, values in annual.items():
        facts[concept] = {
            "units": {
                "USD": [
                    {
                        "fy": year,
                        "fp": "FY",
                        "form": "10-K",
                        "end": f"{year}-12-31",
                        "filed": f"{year + 1}-02-01",
                        "val": value,
                    }
                    for year, value in zip(range(2022, 2026), values, strict=True)
                ]
            }
        }
    quarter_ends = [date(year, month, 28) for year in (2023, 2024, 2025) for month in (3, 6, 9, 12)]
    quarterly: dict[str, tuple[str, list[float | int]]] = {
        "EarningsPerShareDiluted": ("USD/shares", [1 + index / 100 for index in range(12)]),
        "WeightedAverageNumberOfDilutedSharesOutstanding": ("shares", [1_000_000_000] * 12),
    }
    for concept, (unit, quarter_values) in quarterly.items():
        facts[concept] = {
            "units": {
                unit: [
                    {
                        "form": "10-K" if end.month == 12 else "10-Q",
                        "frame": f"CY{end.year}Q{end.month // 3}",
                        "end": end.isoformat(),
                        "filed": (end + timedelta(days=30)).isoformat(),
                        "val": value,
                    }
                    for end, value in zip(quarter_ends, quarter_values, strict=True)
                ]
            }
        }
    for concept, amount in (
        ("NetCashProvidedByUsedInOperatingActivities", 100_000_000_000),
        ("PaymentsToAcquirePropertyPlantAndEquipment", 20_000_000_000),
    ):
        facts[concept]["units"]["USD"].extend(
            {
                "form": "10-K" if end.month == 12 else "10-Q",
                "frame": f"CY{end.year}Q{end.month // 3}",
                "end": end.isoformat(),
                "filed": (end + timedelta(days=30)).isoformat(),
                "val": amount,
            }
            for end in quarter_ends
        )
    return {"facts": {"us-gaap": facts}}


def market_bars() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for year in (2023, 2024, 2025):
        for month in (3, 6, 9, 12):
            rows.append(
                {
                    "timestamp": f"{year}-{month:02d}-28T20:00:00Z",
                    "close": str(90 + len(rows)),
                    "volume": "400000",
                }
            )
    return tuple(rows)


def test_normalizes_four_years_and_eight_prior_quarter_ratios() -> None:
    payload = provider_payload()
    years = normalize_financial_years(payload)
    assert len(years) == 4
    assert years[-1].free_cash_flow == Decimal("184")
    pe, pfcf, eps, fcf_per_share, shares = build_ratio_inputs(
        payload, market_bars(), "https://example.test/sec"
    )
    assert len(pe) == 8 and len(pfcf) == 8
    assert eps is not None and eps > 4
    assert fcf_per_share == Decimal("320")
    assert shares == Decimal("1000000000")


def test_provider_parsers_fail_closed_on_missing_data() -> None:
    with pytest.raises(ProviderError):
        normalize_financial_years({})
    assert build_ratio_inputs({}, (), "https://example.test") == ((), (), None, None, None)
    assert latest_report_date({}) is None
    assert (
        latest_report_date({"filings": {"recent": {"form": ["10-Q"], "filingDate": ["bad"]}}})
        is None
    )


class FakeSec:
    def __init__(self, report_date: date = date(2026, 8, 28)) -> None:
        self.report_date = report_date

    async def company_facts(self, cik: str, now: datetime) -> tuple[dict[str, Any], str, bool]:
        return provider_payload(), "sec:key", False

    async def submissions(self, cik: str, now: datetime) -> tuple[dict[str, Any], str, bool]:
        return (
            {
                "filings": {
                    "recent": {
                        "form": ["10-Q"],
                        "filingDate": [self.report_date.isoformat()],
                    }
                }
            },
            "sec:submissions",
            True,
        )


class FakeAlpaca:
    def __init__(self) -> None:
        self.price = Decimal("100")

    async def asset(self, symbol: str, now: datetime) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "class": "us_equity",
            "exchange": "NASDAQ",
            "tradable": True,
            "status": "active",
            "name": "Provider Corp.",
        }

    async def snapshot(self, symbol: str, now: datetime) -> dict[str, Any]:
        return {
            "price": str(self.price),
            "bid": str(self.price - 1),
            "ask": str(self.price + 1),
            "timestamp": now.isoformat(),
        }

    async def bars(
        self, symbol: str, start: date, end: date, now: datetime
    ) -> tuple[dict[str, Any], ...]:
        return market_bars()

    async def calendar(self, start: date, end: date, now: datetime) -> tuple[date, ...]:
        return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))


class FakeAlpha:
    async def estimates(self, owner_id: str, symbol: str, now: datetime) -> ForwardEstimates:
        return ForwardEstimates(
            comparable_period="2026-12-31",
            consensus_eps=Decimal("2.1"),
            previous_consensus_eps=Decimal("2.0"),
            prior_year_eps=Decimal("1.9"),
            provenance=ProviderProvenance(
                provider="alpha_vantage",
                source_url="https://www.alphavantage.co/documentation/",
                fetched_at=now,
                source_as_of=now.date(),
            ),
        )


@pytest.mark.anyio
async def test_real_provider_analysis_persists_and_reuses_quarterly_freeze() -> None:
    repository = MemoryAnalysisRepository()
    alpaca = FakeAlpaca()
    service = ProviderAnalysisService(
        repository,
        cast(SecEdgarClient, FakeSec()),
        cast(AlpacaReadClient, alpaca),
        cast(AlphaVantageClient, FakeAlpha()),
    )
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    first = await service.analyze("owner", "aapl", now)
    assert first.valuation.report_date == date(2026, 8, 28)
    assert first.valuation.frozen_at == now
    assert len(first.evidence) == 3
    assert all(item.evidence_ids for item in first.criteria)
    assert "next_earnings_schedule_unavailable" in first.no_trade_reasons
    frozen_floor = first.valuation.floor
    alpaca.price = Decimal("80")
    second = await service.analyze("owner", "AAPL", now + timedelta(minutes=1))
    assert second.valuation.floor == frozen_floor
    assert second.valuation.current_price == Decimal("80")
    assert second.valuation.status in {
        ValuationStatus.GREEN,
        ValuationStatus.STRONG_GREEN,
        ValuationStatus.YELLOW,
    }


@pytest.mark.anyio
async def test_post_earnings_wait_keeps_previous_range() -> None:
    repository = MemoryAnalysisRepository()
    alpaca = FakeAlpaca()
    first_service = ProviderAnalysisService(
        repository,
        cast(SecEdgarClient, FakeSec(date(2026, 8, 20))),
        cast(AlpacaReadClient, alpaca),
        cast(AlphaVantageClient, FakeAlpha()),
    )
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    first = await first_service.analyze("owner", "AAPL", now)
    waiting = ProviderAnalysisService(
        repository,
        cast(SecEdgarClient, FakeSec(date(2026, 9, 2))),
        cast(AlpacaReadClient, alpaca),
        cast(AlphaVantageClient, FakeAlpha()),
    )
    second = await waiting.analyze("owner", "AAPL", now)
    assert second.earnings_state == "post_earnings_wait"
    assert second.valuation.floor == first.valuation.floor
    assert "post_earnings_two_session_wait" in second.no_trade_reasons


def test_frozen_repricing_handles_insufficient_and_red() -> None:
    from app.services.analysis import build_fixture_thesis

    frozen = build_fixture_thesis().valuation
    assert _repriced(frozen, Decimal("999")).status == ValuationStatus.RED
    missing = frozen.model_copy(update={"floor": None, "ceiling": None})
    assert _repriced(missing, Decimal("100")).status == ValuationStatus.INSUFFICIENT
