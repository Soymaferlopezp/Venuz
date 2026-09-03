from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.models import FiscalPeriod, ProviderProvenance
from app.integrations.base import AsyncJsonClient, JsonObject, ProviderError

SEC_BASE_URL = "https://data.sec.gov"


class SecEdgarClient:
    def __init__(self, http: AsyncJsonClient, user_agent: str) -> None:
        if "@" not in user_agent:
            raise ValueError("SEC User-Agent must include a contact email")
        self.http = http
        self.user_agent = user_agent

    async def company_facts(self, cik: str, now: datetime) -> tuple[JsonObject, str, bool]:
        padded = cik.zfill(10)
        payload, key, cached = await self.http.get_json(
            f"{SEC_BASE_URL}/api/xbrl/companyfacts/CIK{padded}.json",
            operation="company_facts",
            params={"cik": padded},
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            ttl=timedelta(hours=24),
            now=now,
        )
        if not isinstance(payload, dict):
            raise ProviderError("SEC Company Facts response is invalid")
        return payload, key, cached

    async def submissions(self, cik: str, now: datetime) -> tuple[JsonObject, str, bool]:
        padded = cik.zfill(10)
        payload, key, cached = await self.http.get_json(
            f"{SEC_BASE_URL}/submissions/CIK{padded}.json",
            operation="submissions",
            params={"cik": padded},
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            ttl=timedelta(hours=24),
            now=now,
        )
        if not isinstance(payload, dict):
            raise ProviderError("SEC Submissions response is invalid")
        return payload, key, cached


def parse_company_fact(
    payload: Mapping[str, Any], concept: str, *, unit: str = "USD"
) -> tuple[tuple[FiscalPeriod, Decimal], ...]:
    try:
        entries = payload["facts"]["us-gaap"][concept]["units"][unit]
    except (KeyError, TypeError) as error:
        raise ProviderError(f"SEC fact {concept} is missing") from error
    if not isinstance(entries, list):
        raise ProviderError(f"SEC fact {concept} has invalid units")
    by_period: dict[tuple[int, str, date], tuple[FiscalPeriod, Decimal]] = {}
    for raw in entries:
        if not isinstance(raw, dict) or raw.get("form") not in {"10-K", "10-K/A"}:
            continue
        try:
            fiscal_year = int(raw["fy"])
            fiscal_period = str(raw["fp"])
            end = date.fromisoformat(str(raw["end"]))
            filed = date.fromisoformat(str(raw["filed"])) if raw.get("filed") else None
            value = Decimal(str(raw["val"]))
        except (KeyError, ValueError, InvalidOperation):
            continue
        period = FiscalPeriod(
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            end=end,
            filed_at=filed,
        )
        key = (fiscal_year, fiscal_period, end)
        current = by_period.get(key)
        if current is None or (filed or date.min) >= (current[0].filed_at or date.min):
            by_period[key] = (period, value)
    return tuple(sorted(by_period.values(), key=lambda item: item[0].end))


def sec_provenance(cik: str, fetched_at: datetime, filed_at: date) -> ProviderProvenance:
    return ProviderProvenance(
        provider="sec_edgar",
        source_url=f"https://www.sec.gov/edgar/browse/?CIK={cik.zfill(10)}",
        fetched_at=fetched_at.astimezone(UTC),
        source_as_of=filed_at,
    )
