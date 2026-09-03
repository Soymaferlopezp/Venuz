from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrafficLight(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    INSUFFICIENT = "insufficient"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class ValuationStatus(StrEnum):
    STRONG_GREEN = "strong_green"
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    INSUFFICIENT = "insufficient"


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    NO_TRADE = "no_trade"


class DataState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    INSUFFICIENT = "insufficient"
    PROVIDER_EXHAUSTED = "provider_exhausted"
    ERROR = "error"


class Sector(DomainModel):
    slug: str
    name: str
    prioritized: bool = True


class Company(DomainModel):
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    name: str
    exchange: str
    sector: Sector
    cik: str | None = None


class FiscalPeriod(DomainModel):
    fiscal_year: int
    fiscal_period: str
    start: date | None = None
    end: date
    filed_at: date | None = None


class ProviderProvenance(DomainModel):
    provider: str
    source_url: str
    fetched_at: datetime
    source_as_of: datetime | date
    cache_key: str | None = None
    fresh_until: datetime | None = None

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> ProviderProvenance:
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must include an explicit timezone")
        if self.fresh_until is not None and self.fresh_until.tzinfo is None:
            raise ValueError("fresh_until must include an explicit timezone")
        return self

    @classmethod
    def fixture(cls, provider: str, source_url: str) -> ProviderProvenance:
        observed = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
        return cls(
            provider=provider,
            source_url=source_url,
            fetched_at=observed,
            source_as_of=observed,
        )


class Evidence(DomainModel):
    evidence_id: str
    title: str
    provenance: ProviderProvenance


class FinancialYear(DomainModel):
    period: FiscalPeriod
    revenue: Decimal
    net_income: Decimal
    operating_cash_flow: Decimal
    capital_expenditures: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    total_debt: Decimal

    @property
    def free_cash_flow(self) -> Decimal:
        return self.operating_cash_flow - self.capital_expenditures

    @property
    def shareholders_equity(self) -> Decimal:
        return self.total_assets - self.total_liabilities

    @property
    def net_margin(self) -> Decimal | None:
        if self.revenue == 0:
            return None
        return self.net_income / self.revenue


class ForwardEstimates(DomainModel):
    comparable_period: str
    consensus_eps: Decimal | None
    previous_consensus_eps: Decimal | None
    prior_year_eps: Decimal | None
    provenance: ProviderProvenance


class CriterionResult(DomainModel):
    criterion: str
    status: TrafficLight
    formula: str
    reason: str
    values: dict[str, Decimal | int | str | bool | None]
    evidence_ids: tuple[str, ...] = ()


class RatioObservation(DomainModel):
    ratio_type: str = Field(pattern=r"^(pe|pfcf)$")
    period_end: date
    value: Decimal | None
    included: bool = False
    reason: str | None = None
    source_url: str


class RatioCluster(DomainModel):
    ratio_type: str
    observations: tuple[RatioObservation, ...]
    median: Decimal | None
    confidence: Confidence


class ValuationRange(DomainModel):
    current_price: Decimal
    estimated_price_pe: Decimal | None
    estimated_price_pfcf: Decimal | None
    floor: Decimal | None
    ceiling: Decimal | None
    green_price: Decimal | None
    strong_green_price: Decimal | None
    status: ValuationStatus
    confidence: Confidence
    automatic_action_eligible: bool
    report_date: date | None = None
    frozen_at: datetime | None = None
    refresh_eligible_at: datetime | None = None


class UniverseAsset(DomainModel):
    company: Company
    tradable: bool
    us_listed: bool
    instrument_type: str
    market_cap: Decimal | None
    average_daily_dollar_volume: Decimal | None
    latest_net_income: Decimal | None
    current_price: Decimal | None
    excluded_industry: str | None = None


class UniverseDecision(DomainModel):
    asset: UniverseAsset
    eligibility: Eligibility
    reasons: tuple[str, ...]


class ProviderBudget(DomainModel):
    provider: str
    budget_date: date
    request_limit: int = 25
    request_count: int = 0

    @property
    def remaining(self) -> int:
        return self.request_limit - self.request_count


class MarketContext(DomainModel):
    price: Decimal
    bid: Decimal
    ask: Decimal
    average_daily_dollar_volume: Decimal | None
    observed_at: datetime
    provenance: ProviderProvenance


class CompanyThesis(DomainModel):
    company: Company
    generated_at: datetime
    eligibility: Eligibility
    criteria: tuple[CriterionResult, ...]
    pe_cluster: RatioCluster
    pfcf_cluster: RatioCluster
    valuation: ValuationRange
    evidence: tuple[Evidence, ...]
    no_trade_reasons: tuple[str, ...]
    data_state: DataState = DataState.FRESH
    fresh_until: datetime | None = None
    earnings_state: str = "unknown"
    financial_years: tuple[FinancialYear, ...] = ()
    forward_estimates: ForwardEstimates | None = None
    market: MarketContext | None = None
