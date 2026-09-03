from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.domain.models import DataState
from app.integrations.alpha_vantage import BudgetExhausted
from app.repositories.analysis import SupabaseAnalysisRepository, SupabaseRestStore
from app.services.analysis import build_fixture_thesis


class FakePostgrestClient:
    def __init__(self) -> None:
        self.cache: dict[str, Any] | None = None
        self.analysis: dict[str, Any] | None = None
        self.watchlist: dict[str, Any] | None = None
        self.calls: list[tuple[str, str, Any]] = []
        self.rpc_status = 200
        self.rpc_payload: Any = 24

    def response(self, method: str, url: str, payload: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request(method, url),
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("GET", url, kwargs))
        rows: Any
        if url.endswith("provider_cache_entries"):
            rows = [{"payload": self.cache}] if self.cache is not None else []
        elif url.endswith("provider_budgets"):
            rows = [
                {
                    "provider": "alpha_vantage",
                    "budget_date": "2026-09-02",
                    "request_limit": 25,
                    "request_count": 4,
                }
            ]
        else:
            rows = []
        return self.response("GET", url, rows)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("POST", url, kwargs))
        if url.endswith("provider_cache_entries"):
            self.cache = kwargs["json"]["payload"]
            return self.response("POST", url, [])
        if url.endswith("rpc/reserve_provider_budget"):
            return httpx.Response(
                self.rpc_status,
                json=self.rpc_payload,
                request=httpx.Request("POST", url),
            )
        return self.response("POST", url, [])

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        table = url.rsplit("/", 1)[-1]
        payload = kwargs.get("json")
        if method == "GET" and table == "analysis_snapshots":
            rows = [self.analysis] if self.analysis is not None else []
            return self.response(method, url, rows)
        if method == "GET" and table == "watchlist_snapshots":
            rows = [self.watchlist] if self.watchlist is not None else []
            return self.response(method, url, rows)
        if method == "POST" and table == "analysis_snapshots":
            assert isinstance(payload, dict)
            self.analysis = {
                "thesis": payload["thesis"],
                "fresh_until": payload["fresh_until"],
            }
        if method == "POST" and table == "watchlist_snapshots":
            assert isinstance(payload, dict)
            self.watchlist = {"items": payload["items"]}
        if method == "PATCH":
            return httpx.Response(204, request=httpx.Request(method, url))
        if isinstance(payload, list):
            return self.response(method, url, [])
        row = dict(payload or {})
        row.setdefault("id", f"{table}-id")
        return self.response(method, url, [row])


@pytest.mark.anyio
async def test_supabase_cache_budget_and_exhaustion() -> None:
    client = FakePostgrestClient()
    store = SupabaseRestStore("https://example.supabase.co", "server-secret", client)  # type: ignore[arg-type]
    now = datetime(2026, 9, 2, 18, tzinfo=UTC)
    assert await store.get("alpaca:test:key", now) is None
    await store.put(
        "alpaca:test:key",
        {"symbol": "AAPL", "period": "2026-Q3", "source_as_of": now.isoformat()},
        now + timedelta(minutes=1),
    )
    assert await store.get("alpaca:test:key", now) == {
        "symbol": "AAPL",
        "period": "2026-Q3",
        "source_as_of": now.isoformat(),
    }
    assert await store.reserve("owner", "alpha_vantage", now.date(), 25) == 24
    budget = await store.provider_budget("owner", "alpha_vantage", now.date())
    assert budget.request_count == 4 and budget.remaining == 21
    client.rpc_status = 409
    client.rpc_payload = {"message": "exhausted"}
    with pytest.raises(BudgetExhausted):
        await store.reserve("owner", "alpha_vantage", now.date(), 25)


@pytest.mark.anyio
async def test_supabase_repository_persists_reads_freeze_watchlist_and_job() -> None:
    client = FakePostgrestClient()
    store = SupabaseRestStore("https://example.supabase.co", "server-secret", client)  # type: ignore[arg-type]
    repository = SupabaseAnalysisRepository(store)
    owner = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(UTC)
    thesis = build_fixture_thesis(now=now)
    await repository.save_thesis(owner, thesis)
    latest = await repository.latest_thesis(owner, "aapl")
    assert latest is not None and latest.company.ticker == "AAPL"
    frozen = await repository.frozen_thesis(owner, "AAPL", thesis.valuation.report_date or date.min)
    assert frozen is not None
    await repository.save_watchlist(owner, (thesis,))
    watchlist = await repository.latest_watchlist(owner)
    assert len(watchlist) == 1
    job_id = await repository.start_job(owner, "daily-scan", "scan")
    await repository.finish_job(job_id, succeeded=True)
    await repository.finish_job(job_id, succeeded=False, failure_code="provider_error")
    assert any(call[0] == "PATCH" and call[1].endswith("job_runs") for call in client.calls)


@pytest.mark.anyio
async def test_latest_persisted_analysis_is_marked_stale_and_missing_is_empty() -> None:
    client = FakePostgrestClient()
    store = SupabaseRestStore("https://example.supabase.co", "server-secret", client)  # type: ignore[arg-type]
    repository = SupabaseAnalysisRepository(store)
    assert await repository.latest_thesis("owner", "AAPL") is None
    thesis = build_fixture_thesis()
    client.analysis = {
        "thesis": thesis.model_dump(mode="json"),
        "fresh_until": "2020-01-01T00:00:00+00:00",
    }
    stale = await repository.latest_thesis("owner", "AAPL")
    assert stale is not None
    assert stale.data_state == DataState.STALE
    assert "analysis_stale" in stale.no_trade_reasons
    client.watchlist = None
    assert await repository.latest_watchlist("owner") == ()
