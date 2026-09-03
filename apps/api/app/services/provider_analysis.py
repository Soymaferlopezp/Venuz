from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.calendar import EarningsState, earnings_state, should_recalculate
from app.domain.fundamentals import evaluate_fundamentals
from app.domain.models import (
    Company,
    CompanyThesis,
    Confidence,
    DataState,
    Eligibility,
    Evidence,
    FinancialYear,
    FiscalPeriod,
    MarketContext,
    ProviderProvenance,
    RatioObservation,
    Sector,
    TrafficLight,
    UniverseAsset,
    ValuationRange,
    ValuationStatus,
)
from app.domain.universe import evaluate_asset
from app.domain.valuation import build_valuation_range, select_coherent_cluster, valuation_criterion
from app.integrations.alpaca import AlpacaReadClient
from app.integrations.alpha_vantage import AlphaVantageClient
from app.integrations.base import JsonObject, ProviderError
from app.integrations.sec import SecEdgarClient, parse_company_fact, sec_provenance
from app.repositories.analysis import AnalysisRepository


@dataclass(frozen=True)
class CompanySpec:
    symbol: str
    cik: str
    name: str
    exchange: str
    sector_slug: str
    sector_name: str
    excluded_industry: str | None = None


COMPANY_SPECS = {
    item.symbol: item
    for item in (
        CompanySpec("AAPL", "0000320193", "Apple Inc.", "NASDAQ", "technology", "Technology"),
        CompanySpec("MSFT", "0000789019", "Microsoft Corp.", "NASDAQ", "technology", "Technology"),
        CompanySpec("NVDA", "0001045810", "NVIDIA Corp.", "NASDAQ", "technology", "Technology"),
        CompanySpec("GOOGL", "0001652044", "Alphabet Inc.", "NASDAQ", "technology", "Technology"),
        CompanySpec(
            "AMZN",
            "0001018724",
            "Amazon.com Inc.",
            "NASDAQ",
            "consumer-discretionary",
            "Consumer discretionary",
        ),
        CompanySpec(
            "META", "0001326801", "Meta Platforms Inc.", "NASDAQ", "technology", "Technology"
        ),
        CompanySpec("AVGO", "0001730168", "Broadcom Inc.", "NASDAQ", "technology", "Technology"),
        CompanySpec("LLY", "0000059478", "Eli Lilly and Co.", "NYSE", "health-care", "Health care"),
        CompanySpec(
            "COST",
            "0000909832",
            "Costco Wholesale Corp.",
            "NASDAQ",
            "consumer-staples",
            "Consumer staples",
        ),
        CompanySpec("XOM", "0000034088", "Exxon Mobil Corp.", "NYSE", "energy", "Energy"),
    )
}

ANNUAL_CONCEPTS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "total_debt": (
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    ),
}


def _series(
    payload: Mapping[str, Any], concepts: Sequence[str]
) -> tuple[tuple[FiscalPeriod, Decimal], ...]:
    for concept in concepts:
        try:
            values = parse_company_fact(payload, concept)
        except ProviderError:
            continue
        if len(values) >= 4:
            return values
    raise ProviderError(f"SEC concepts unavailable: {concepts[0]}")


def normalize_financial_years(payload: Mapping[str, Any]) -> tuple[FinancialYear, ...]:
    values = {name: _series(payload, concepts) for name, concepts in ANNUAL_CONCEPTS.items()}
    indexed = {name: {item[0].fiscal_year: item for item in rows} for name, rows in values.items()}
    common = sorted(set.intersection(*(set(rows) for rows in indexed.values())))[-4:]
    if len(common) < 4:
        raise ProviderError("SEC does not contain four aligned fiscal years")
    years: list[FinancialYear] = []
    for fiscal_year in common:
        period = indexed["revenue"][fiscal_year][0]
        capex = abs(indexed["capital_expenditures"][fiscal_year][1])
        years.append(
            FinancialYear(
                period=period,
                revenue=indexed["revenue"][fiscal_year][1],
                net_income=indexed["net_income"][fiscal_year][1],
                operating_cash_flow=indexed["operating_cash_flow"][fiscal_year][1],
                capital_expenditures=capex,
                total_assets=indexed["total_assets"][fiscal_year][1],
                total_liabilities=indexed["total_liabilities"][fiscal_year][1],
                total_debt=indexed["total_debt"][fiscal_year][1],
            )
        )
    return tuple(years)


def _quarterly_fact(
    payload: Mapping[str, Any], concepts: Sequence[str], unit: str
) -> dict[date, Decimal]:
    for concept in concepts:
        try:
            entries = payload["facts"]["us-gaap"][concept]["units"][unit]
        except (KeyError, TypeError):
            continue
        result: dict[date, tuple[date, Decimal]] = {}
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict) or item.get("form") not in {
                "10-Q",
                "10-K",
                "10-Q/A",
                "10-K/A",
            }:
                continue
            frame = str(item.get("frame", ""))
            if re.fullmatch(r"CY[0-9]{4}Q[1-4]", frame) is None:
                continue
            try:
                end = date.fromisoformat(str(item["end"]))
                filed = date.fromisoformat(str(item["filed"]))
                value = Decimal(str(item["val"]))
            except (KeyError, ValueError, InvalidOperation):
                continue
            if end not in result or filed >= result[end][0]:
                result[end] = (filed, value)
        if result:
            return {end: row[1] for end, row in result.items()}
    return {}


def _bar_rows(bars: Sequence[JsonObject]) -> list[tuple[date, Decimal, Decimal]]:
    result: list[tuple[date, Decimal, Decimal]] = []
    for item in bars:
        try:
            observed = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00")).date()
            result.append((observed, Decimal(str(item["close"])), Decimal(str(item["volume"]))))
        except (KeyError, ValueError, InvalidOperation):
            continue
    return sorted(result)


def build_ratio_inputs(
    payload: Mapping[str, Any], bars: Sequence[JsonObject], source_url: str
) -> tuple[
    tuple[RatioObservation, ...],
    tuple[RatioObservation, ...],
    Decimal | None,
    Decimal | None,
    Decimal | None,
]:
    eps = _quarterly_fact(payload, ("EarningsPerShareDiluted",), "USD/shares")
    ocf = _quarterly_fact(payload, ("NetCashProvidedByUsedInOperatingActivities",), "USD")
    capex = _quarterly_fact(payload, ("PaymentsToAcquirePropertyPlantAndEquipment",), "USD")
    shares = _quarterly_fact(
        payload,
        ("WeightedAverageNumberOfDilutedSharesOutstanding",),
        "shares",
    )
    periods = sorted(set(eps) & set(ocf) & set(capex) & set(shares))
    bar_rows = _bar_rows(bars)
    pe: list[RatioObservation] = []
    pfcf: list[RatioObservation] = []
    current_eps: Decimal | None = None
    current_fcf_per_share: Decimal | None = None
    latest_shares: Decimal | None = None
    for index in range(3, len(periods)):
        window = periods[index - 3 : index + 1]
        period = periods[index]
        ttm_eps = sum((eps[item] for item in window), Decimal(0))
        ttm_fcf = sum((ocf[item] - abs(capex[item]) for item in window), Decimal(0))
        diluted = shares[period]
        closes = [row[1] for row in bar_rows if row[0] <= period]
        close = closes[-1] if closes else None
        if index == len(periods) - 1:
            current_eps = ttm_eps
            current_fcf_per_share = ttm_fcf / diluted if diluted > 0 else None
            latest_shares = diluted
            continue
        pe_value = close / ttm_eps if close is not None and ttm_eps > 0 else None
        pfcf_value = (
            close / (ttm_fcf / diluted)
            if close is not None and ttm_fcf > 0 and diluted > 0
            else None
        )
        pe.append(
            RatioObservation(
                ratio_type="pe", period_end=period, value=pe_value, source_url=source_url
            )
        )
        pfcf.append(
            RatioObservation(
                ratio_type="pfcf", period_end=period, value=pfcf_value, source_url=source_url
            )
        )
    return tuple(pe[-8:]), tuple(pfcf[-8:]), current_eps, current_fcf_per_share, latest_shares


def latest_report_date(payload: Mapping[str, Any]) -> date | None:
    recent = payload.get("filings")
    recent = recent.get("recent") if isinstance(recent, dict) else None
    if not isinstance(recent, dict):
        return None
    forms = recent.get("form")
    filed = recent.get("filingDate")
    if not isinstance(forms, list) or not isinstance(filed, list):
        return None
    for form, filed_at in zip(forms, filed, strict=False):
        if form in {"10-Q", "10-K"}:
            try:
                return date.fromisoformat(str(filed_at))
            except ValueError:
                return None
    return None


def _evidence_id(provider: str, source_url: str, as_of: object) -> str:
    value = f"{provider}:{source_url}:{as_of}"
    return hashlib.sha256(value.encode()).hexdigest()


def _repriced(frozen: ValuationRange, current_price: Decimal) -> ValuationRange:
    floor = frozen.floor
    ceiling = frozen.ceiling
    if floor is None or ceiling is None:
        status = ValuationStatus.INSUFFICIENT
    elif current_price > ceiling:
        status = ValuationStatus.RED
    elif frozen.confidence in {Confidence.LOW, Confidence.INSUFFICIENT}:
        status = ValuationStatus.YELLOW
    elif current_price <= floor * Decimal("0.90"):
        status = ValuationStatus.STRONG_GREEN
    elif current_price <= floor * Decimal("0.95"):
        status = ValuationStatus.GREEN
    else:
        status = ValuationStatus.YELLOW
    return frozen.model_copy(
        update={
            "current_price": current_price,
            "status": status,
            "automatic_action_eligible": (
                status in {ValuationStatus.GREEN, ValuationStatus.STRONG_GREEN}
                and frozen.confidence in {Confidence.MEDIUM, Confidence.HIGH}
            ),
        }
    )


class ProviderAnalysisService:
    def __init__(
        self,
        repository: AnalysisRepository,
        sec: SecEdgarClient,
        alpaca: AlpacaReadClient,
        alpha: AlphaVantageClient,
    ) -> None:
        self.repository = repository
        self.sec = sec
        self.alpaca = alpaca
        self.alpha = alpha

    async def analyze(self, owner_id: str, symbol: str, now: datetime) -> CompanyThesis:
        normalized_symbol = symbol.upper()
        spec = COMPANY_SPECS.get(normalized_symbol)
        if spec is None:
            raise ProviderError("Symbol is outside the reviewed Phase 2 universe")
        facts, _, facts_cached = await self.sec.company_facts(spec.cik, now)
        submissions, _, submissions_cached = await self.sec.submissions(spec.cik, now)
        asset = await self.alpaca.asset(normalized_symbol, now)
        snapshot = await self.alpaca.snapshot(normalized_symbol, now)
        bars = await self.alpaca.bars(
            normalized_symbol, now.date() - timedelta(days=1460), now.date(), now
        )
        estimates = await self.alpha.estimates(owner_id, normalized_symbol, now)
        years = normalize_financial_years(facts)
        report_date = latest_report_date(submissions)
        sessions = await self.alpaca.calendar(
            (report_date or now.date()) - timedelta(days=10),
            now.date() + timedelta(days=10),
            now,
        )
        state = earnings_state(now.date(), sessions, report_date, None)
        source_url = f"https://www.sec.gov/edgar/browse/?CIK={spec.cik}"
        pe_rows, pfcf_rows, ttm_eps, fcf_per_share, shares = build_ratio_inputs(
            facts, bars, source_url
        )
        price = Decimal(str(snapshot["price"]))
        current_pe = price / ttm_eps if ttm_eps is not None and ttm_eps > 0 else None
        current_pfcf = (
            price / fcf_per_share if fcf_per_share is not None and fcf_per_share > 0 else None
        )
        pe_cluster = select_coherent_cluster("pe", pe_rows)
        pfcf_cluster = select_coherent_cluster("pfcf", pfcf_rows)
        frozen = (
            await self.repository.frozen_thesis(owner_id, normalized_symbol, report_date)
            if report_date is not None
            else None
        )
        previous = await self.repository.latest_thesis(owner_id, normalized_symbol)
        can_recalculate = report_date is not None and should_recalculate(
            now.date(), sessions, report_date, None
        )
        if frozen is not None:
            valuation = _repriced(frozen.valuation, price)
            pe_cluster = frozen.pe_cluster
            pfcf_cluster = frozen.pfcf_cluster
        elif state == EarningsState.POST_EARNINGS_WAIT and previous is not None:
            valuation = _repriced(previous.valuation, price)
        elif can_recalculate:
            valuation = build_valuation_range(
                price, current_pe, current_pfcf, pe_cluster, pfcf_cluster
            ).model_copy(update={"report_date": report_date, "frozen_at": now})
        else:
            valuation = ValuationRange(
                current_price=price,
                estimated_price_pe=None,
                estimated_price_pfcf=None,
                floor=None,
                ceiling=None,
                green_price=None,
                strong_green_price=None,
                status=ValuationStatus.INSUFFICIENT,
                confidence=Confidence.INSUFFICIENT,
                automatic_action_eligible=False,
                report_date=report_date,
            )
        sec_as_of = max(year.period.filed_at or year.period.end for year in years)
        sec_prov = sec_provenance(spec.cik, now, sec_as_of).model_copy(
            update={
                "cache_key": "cache-hit"
                if facts_cached and submissions_cached
                else "provider-read",
                "fresh_until": now + timedelta(hours=24),
            }
        )
        alpha_prov = estimates.provenance.model_copy(
            update={"fresh_until": now + timedelta(hours=24)}
        )
        alpaca_prov = ProviderProvenance(
            provider="alpaca",
            source_url="https://docs.alpaca.markets/docs/market-data",
            fetched_at=now,
            source_as_of=datetime.fromisoformat(str(snapshot["timestamp"]).replace("Z", "+00:00")),
            fresh_until=now + timedelta(minutes=1),
        )
        evidence = (
            Evidence(
                evidence_id=_evidence_id("sec_edgar", source_url, sec_as_of),
                title="SEC Company Facts and filing history",
                provenance=sec_prov,
            ),
            Evidence(
                evidence_id=_evidence_id(
                    "alpha_vantage", alpha_prov.source_url, alpha_prov.source_as_of
                ),
                title="Alpha Vantage consensus estimate and revisions",
                provenance=alpha_prov,
            ),
            Evidence(
                evidence_id=_evidence_id(
                    "alpaca", alpaca_prov.source_url, alpaca_prov.source_as_of
                ),
                title="Alpaca asset, quote, bars, and exchange calendar",
                provenance=alpaca_prov,
            ),
        )
        criteria = list(evaluate_fundamentals(years, estimates))
        criteria.append(valuation_criterion(valuation))
        criteria = [
            item.model_copy(
                update={
                    "evidence_ids": (
                        (evidence[1].evidence_id,)
                        if item.criterion == "forward_estimates"
                        else (
                            (evidence[0].evidence_id, evidence[2].evidence_id)
                            if item.criterion == "self_relative_valuation"
                            else (evidence[0].evidence_id,)
                        )
                    )
                }
            )
            for item in criteria
        ]
        bar_values = _bar_rows(bars)[-20:]
        dollar_volume = (
            sum((close * volume for _, close, volume in bar_values), Decimal(0))
            / Decimal(len(bar_values))
            if bar_values
            else None
        )
        company = Company(
            ticker=normalized_symbol,
            name=str(asset.get("name") or spec.name),
            exchange=str(asset["exchange"]),
            sector=Sector(slug=spec.sector_slug, name=spec.sector_name),
            cik=spec.cik,
        )
        universe = evaluate_asset(
            UniverseAsset(
                company=company,
                tradable=bool(asset["tradable"]),
                us_listed=asset["class"] == "us_equity",
                instrument_type="equity" if asset["class"] == "us_equity" else str(asset["class"]),
                market_cap=price * shares if shares is not None else None,
                average_daily_dollar_volume=dollar_volume,
                latest_net_income=years[-1].net_income,
                current_price=price,
                excluded_industry=spec.excluded_industry,
            )
        )
        reasons = list(universe.reasons)
        reasons.extend(
            f"{item.criterion}:{item.status.value}"
            for item in criteria
            if item.status in {TrafficLight.RED, TrafficLight.INSUFFICIENT}
        )
        if state == EarningsState.POST_EARNINGS_WAIT:
            reasons.append("post_earnings_two_session_wait")
        reasons.append("next_earnings_schedule_unavailable")
        thesis = CompanyThesis(
            company=company,
            generated_at=now.astimezone(UTC),
            eligibility=Eligibility.NO_TRADE if reasons else Eligibility.ELIGIBLE,
            criteria=tuple(criteria),
            pe_cluster=pe_cluster,
            pfcf_cluster=pfcf_cluster,
            valuation=valuation,
            evidence=evidence,
            no_trade_reasons=tuple(dict.fromkeys(reasons)),
            data_state=DataState.FRESH,
            fresh_until=now + timedelta(minutes=1),
            earnings_state=state.value,
            financial_years=years,
            forward_estimates=estimates,
            market=MarketContext(
                price=price,
                bid=Decimal(str(snapshot["bid"])),
                ask=Decimal(str(snapshot["ask"])),
                average_daily_dollar_volume=dollar_volume,
                observed_at=datetime.fromisoformat(
                    str(snapshot["timestamp"]).replace("Z", "+00:00")
                ),
                provenance=alpaca_prov,
            ),
        )
        await self.repository.save_thesis(owner_id, thesis)
        return thesis
