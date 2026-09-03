from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.integrations.alpaca import (
    parse_asset,
    parse_bars,
    parse_calendar,
    parse_news,
    parse_snapshot,
)
from app.integrations.alpha_vantage import BudgetExhausted, MemoryBudgetStore, parse_estimates
from app.integrations.base import AsyncJsonClient, MemoryCacheStore, ProviderError, cache_key
from app.integrations.sec import SecEdgarClient, parse_company_fact, sec_provenance

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict[str, object]:
    value: object = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_sec_company_facts_parsing_and_provenance() -> None:
    values = parse_company_fact(fixture("sec_companyfacts.json"), "Revenues")
    assert [value for _, value in values] == [1000, 1100]
    provenance = sec_provenance("320193", datetime(2026, 9, 2, tzinfo=UTC), date(2025, 11, 1))
    assert provenance.provider == "sec_edgar"
    assert "0000320193" in provenance.source_url


def test_sec_invalid_payload_fails_closed() -> None:
    with pytest.raises(ProviderError, match="missing"):
        parse_company_fact({}, "Revenues")
    with pytest.raises(ValueError, match="contact email"):
        SecEdgarClient(object(), "Venuz")  # type: ignore[arg-type]


def test_alpaca_contract_parsers() -> None:
    snapshot = parse_snapshot(fixture("alpaca_snapshot.json"))
    assert snapshot["price"] == "140.25"
    asset = parse_asset(
        {
            "symbol": "AAPL",
            "class": "us_equity",
            "exchange": "NASDAQ",
            "tradable": True,
            "status": "active",
        }
    )
    assert asset["tradable"] is True
    assert parse_calendar([{"date": "2026-09-01"}, {"date": "2026-09-02"}]) == (
        date(2026, 9, 1),
        date(2026, 9, 2),
    )
    news = parse_news(
        {
            "news": [
                {
                    "id": 1,
                    "headline": "Fixture",
                    "url": "https://example.test",
                    "created_at": "2026-09-02T00:00:00Z",
                }
            ]
        }
    )
    assert news[0]["headline"] == "Fixture"
    bars = parse_bars(
        {"bars": {"AAPL": [{"t": "2026-09-02T20:00:00Z", "c": 100, "v": 5}]}},
        "AAPL",
    )
    assert bars[0]["close"] == "100"


def test_alpaca_contradictory_or_missing_data_fails_closed() -> None:
    with pytest.raises(ProviderError, match="contradictory"):
        parse_snapshot({"latestTrade": {"p": 10}, "latestQuote": {"bp": 11, "ap": 10}})
    with pytest.raises(ProviderError, match="incomplete"):
        parse_asset({})
    with pytest.raises(ProviderError, match="invalid"):
        parse_calendar({})
    with pytest.raises(ProviderError, match="invalid"):
        parse_news({})
    with pytest.raises(ProviderError, match="invalid"):
        parse_bars({"bars": "bad"}, "AAPL")
    with pytest.raises(ProviderError, match="contradictory"):
        parse_bars({"bars": [{"t": "now", "c": -1, "v": 1}]}, "AAPL")


def test_alpha_estimates_and_quota_payload() -> None:
    parsed = parse_estimates(
        fixture("alpha_estimates.json"), "AAPL", datetime(2026, 9, 2, tzinfo=UTC)
    )
    assert parsed.consensus_eps is not None and parsed.consensus_eps > parsed.previous_consensus_eps  # type: ignore[operator]
    with pytest.raises(BudgetExhausted):
        parse_estimates({"Note": "quota"}, "AAPL", datetime(2026, 9, 2, tzinfo=UTC))
    with pytest.raises(ProviderError, match="missing"):
        parse_estimates({}, "AAPL", datetime(2026, 9, 2, tzinfo=UTC))


@pytest.mark.anyio
async def test_budget_hard_limit_is_persistent_by_owner_and_utc_date() -> None:
    store = MemoryBudgetStore()
    today = date(2026, 9, 2)
    assert await store.reserve("owner", "alpha_vantage", today, 2) == 1
    assert await store.reserve("owner", "alpha_vantage", today, 2) == 0
    with pytest.raises(BudgetExhausted):
        await store.reserve("owner", "alpha_vantage", today, 2)
    assert await store.reserve("owner", "alpha_vantage", date(2026, 9, 3), 2) == 1


@pytest.mark.anyio
async def test_http_cache_is_idempotent_and_retries_are_bounded() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(200, json={"ok": True})

    cache = MemoryCacheStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = AsyncJsonClient(provider="fixture", client=client, cache=cache, sleep=_no_sleep)
        now = datetime(2026, 9, 2, tzinfo=UTC)
        first = await http.get_json(
            "https://example.test",
            operation="read",
            params={"symbol": "AAPL"},
            headers={},
            ttl=timedelta(hours=1),
            now=now,
        )
        second = await http.get_json(
            "https://example.test",
            operation="read",
            params={"symbol": "AAPL"},
            headers={},
            ttl=timedelta(hours=1),
            now=now,
        )
    assert attempts == 2
    assert first[2] is False and second[2] is True
    assert cache_key("fixture", "read", {"symbol": "AAPL"}) == first[1]


async def _no_sleep(_: float) -> None:
    return None
