from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from app.integrations.alpaca import AlpacaReadClient
from app.integrations.alpha_vantage import AlphaVantageClient, MemoryBudgetStore
from app.integrations.base import AsyncJsonClient, MemoryCacheStore, ProviderError
from app.integrations.sec import SecEdgarClient
from app.repositories.analysis import MemoryAnalysisRepository, SupabaseRestStore
from app.services.analysis import build_fixture_thesis

NOW = datetime(2026, 9, 2, 18, 0, tzinfo=UTC)


async def no_sleep(_: float) -> None:
    return None


@pytest.mark.anyio
async def test_all_read_only_clients_parse_mocked_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "companyfacts" in path:
            return httpx.Response(200, json={"facts": {}})
        if "submissions" in path:
            return httpx.Response(200, json={"cik": "0000320193"})
        if "/assets/" in path:
            return httpx.Response(
                200,
                json={
                    "symbol": "AAPL",
                    "class": "us_equity",
                    "exchange": "NASDAQ",
                    "tradable": True,
                    "status": "active",
                },
            )
        if "snapshot" in path:
            assert "symbol" not in request.url.params
            return httpx.Response(
                200,
                json={
                    "latestTrade": {"p": 100, "t": "2026-09-02T18:00:00Z"},
                    "latestQuote": {"bp": 99, "ap": 101},
                },
            )
        if path.endswith("/bars"):
            return httpx.Response(
                200,
                json={"bars": {"AAPL": [{"t": "2026-09-01T20:00:00Z", "c": 100, "v": 300000}]}},
            )
        if "calendar" in path:
            return httpx.Response(200, json=[{"date": "2026-09-01"}, {"date": "2026-09-02"}])
        if "news" in path:
            return httpx.Response(
                200,
                json={
                    "news": [
                        {
                            "id": 1,
                            "headline": "Fixture",
                            "url": "https://example.test",
                            "created_at": "2026-09-02T00:00:00Z",
                        }
                    ]
                },
            )
        if request.url.params.get("function") == "EARNINGS_ESTIMATES":
            assert request.url.params.get("apikey") == "private-test-key"
            return httpx.Response(
                200,
                json={
                    "quarterlyEstimates": [
                        {
                            "date": "2026-12-31",
                            "estimatedEPSAvg": "2",
                            "estimatedEPSAvg7DaysAgo": "1.9",
                            "priorYearEPS": "1.8",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = MemoryCacheStore()
        sec_http = AsyncJsonClient(provider="sec_edgar", client=client, cache=cache, sleep=no_sleep)
        sec = SecEdgarClient(sec_http, "Venuz test@example.com")
        assert (await sec.company_facts("320193", NOW))[0] == {"facts": {}}
        assert (await sec.submissions("320193", NOW))[0]["cik"] == "0000320193"

        alpaca_http = AsyncJsonClient(provider="alpaca", client=client, cache=cache, sleep=no_sleep)
        alpaca = AlpacaReadClient(alpaca_http, "paper-key", "paper-secret")
        assert (await alpaca.asset("AAPL", NOW))["tradable"] is True
        assert (await alpaca.snapshot("AAPL", NOW))["price"] == "100"
        assert len(await alpaca.bars("AAPL", date(2026, 9, 1), date(2026, 9, 2), NOW)) == 1
        assert len(await alpaca.calendar(date(2026, 9, 1), date(2026, 9, 2), NOW)) == 2
        assert (await alpaca.news("AAPL", NOW))[0]["headline"] == "Fixture"

        budget = MemoryBudgetStore()
        alpha_http = AsyncJsonClient(
            provider="alpha_vantage", client=client, cache=cache, sleep=no_sleep
        )
        alpha = AlphaVantageClient(alpha_http, budget, "private-test-key")
        assert (await alpha.estimates("owner", "AAPL", NOW)).consensus_eps is not None
        assert (await alpha.estimates("owner", "AAPL", NOW)).consensus_eps is not None
        assert budget.counts[("owner", "alpha_vantage", NOW.date())] == 1


@pytest.mark.anyio
async def test_http_failures_are_bounded_and_sanitized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"Note": "quota"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = AsyncJsonClient(
            provider="alpha_vantage", client=client, cache=MemoryCacheStore(), sleep=no_sleep
        )
        with pytest.raises(ProviderError, match="quota exhausted"):
            await http.get_json(
                "https://example.test",
                operation="quota",
                params={},
                headers={},
                ttl=__import__("datetime").timedelta(0),
                now=NOW,
                retry_quota=False,
            )
    with pytest.raises(ValueError, match="cannot exceed 25"):
        AlphaVantageClient(http, MemoryBudgetStore(), "key", 26)


@pytest.mark.anyio
async def test_memory_analysis_repository_is_owner_scoped() -> None:
    repository = MemoryAnalysisRepository()
    thesis = build_fixture_thesis()
    await repository.save_thesis("one", thesis)
    assert await repository.latest_thesis("one", "AAPL") == thesis
    assert await repository.latest_thesis("two", "AAPL") is None
    await repository.save_watchlist("one", (thesis,))
    assert await repository.latest_watchlist("one") == (thesis,)
    assert await repository.latest_watchlist("two") == ()


@pytest.mark.anyio
async def test_supabase_store_uses_cache_upsert_atomic_budget_and_owner_filter() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("reserve_provider_budget"):
            return httpx.Response(200, json=24)
        if request.method == "POST":
            return httpx.Response(201, json={})
        if "provider_budgets" in request.url.path:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SupabaseRestStore("https://fixture.supabase.co", "server-secret", client)
        assert await store.get("alpaca:key", NOW) is None
        await store.put("alpaca:key", {"ok": True}, NOW)
        assert await store.reserve("owner", "alpha_vantage", NOW.date(), 25) == 24
        budget = await store.provider_budget("owner", "alpha_vantage", NOW.date())
    assert budget.request_count == 0
    assert any("owner_id=eq.owner" in str(call.url) for call in calls)
    assert all("server-secret" not in str(call.url) for call in calls)
