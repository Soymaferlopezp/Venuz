from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.domain.models import ForwardEstimates, ProviderProvenance
from app.integrations.base import AsyncJsonClient, ProviderError


class BudgetExhausted(ProviderError):
    pass


class BudgetStore(Protocol):
    async def reserve(self, owner_id: str, provider: str, budget_date: date, limit: int) -> int: ...


class MemoryBudgetStore:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, date], int] = {}

    async def reserve(self, owner_id: str, provider: str, budget_date: date, limit: int) -> int:
        key = (owner_id, provider, budget_date)
        count = self.counts.get(key, 0)
        if count >= limit:
            raise BudgetExhausted("Alpha Vantage daily budget exhausted")
        self.counts[key] = count + 1
        return limit - self.counts[key]


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, "None", ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ProviderError("Alpha Vantage estimate is invalid") from error
    return result if result.is_finite() else None


def parse_estimates(
    payload: Mapping[str, Any], symbol: str, fetched_at: datetime
) -> ForwardEstimates:
    if "Note" in payload or "Information" in payload:
        raise BudgetExhausted("Alpha Vantage quota response received")
    rows = payload.get("quarterlyEstimates")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ProviderError("Alpha Vantage estimates are missing")
    row = rows[0]
    period = str(row.get("date", ""))
    current = _optional_decimal(row.get("estimatedEPSAvg"))
    previous = _optional_decimal(
        row.get("estimatedEPSAvg7DaysAgo", row.get("estimatedEPSAvg30DaysAgo"))
    )
    prior_year = _optional_decimal(row.get("priorYearEPS"))
    return ForwardEstimates(
        comparable_period=period,
        consensus_eps=current,
        previous_consensus_eps=previous,
        prior_year_eps=prior_year,
        provenance=ProviderProvenance(
            provider="alpha_vantage",
            source_url=f"https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol={symbol}",
            fetched_at=fetched_at,
            source_as_of=date.fromisoformat(period) if period else fetched_at.date(),
        ),
    )


class AlphaVantageClient:
    def __init__(
        self, http: AsyncJsonClient, budget: BudgetStore, api_key: str, daily_limit: int = 25
    ) -> None:
        if daily_limit > 25:
            raise ValueError("Alpha Vantage budget cannot exceed 25 requests/day")
        self.http = http
        self.budget = budget
        self.api_key = api_key
        self.daily_limit = daily_limit

    async def estimates(self, owner_id: str, symbol: str, now: datetime) -> ForwardEstimates:
        params = {"function": "EARNINGS_ESTIMATES", "symbol": symbol, "apikey": self.api_key}
        # Read cache first so cache hits never consume scarce budget.
        public_params = {"function": params["function"], "symbol": symbol}
        from app.integrations.base import cache_key

        key = cache_key("alpha_vantage", "earnings_estimates", public_params)
        cached = await self.http.cache.get(key, now)
        if cached is not None:
            if not isinstance(cached, dict):
                raise ProviderError("Alpha Vantage cached estimates are invalid")
            return parse_estimates(cached, symbol, now)
        await self.budget.reserve(owner_id, "alpha_vantage", now.date(), self.daily_limit)
        payload, _, _ = await self.http.get_json(
            "https://www.alphavantage.co/query",
            operation="earnings_estimates",
            params=params,
            headers={},
            ttl=timedelta(hours=24),
            now=now,
            retry_quota=False,
            cache_params=public_params,
        )
        if not isinstance(payload, dict):
            raise ProviderError("Alpha Vantage estimates response is invalid")
        return parse_estimates(payload, symbol, now)
