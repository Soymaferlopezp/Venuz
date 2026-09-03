from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.repositories.cycles import SupabaseCycleRepository

ROW = {
    "cycle_id": "cycle-1",
    "cycle_key": "v:2026-09-03:cutoff",
    "state": "queued",
    "data_freshness": "cached",
    "paper_order_submitted": False,
    "blocked_reasons": [],
    "evidence_links": ["https://www.sec.gov/"],
    "provider_provenance": ["sec_edgar"],
    "events": [
        {"state": "queued", "occurred_at": "2026-09-03T00:00:00Z", "message": "Cycle queued"}
    ],
    "updated_at": "2026-09-03T00:00:00Z",
}


@pytest.mark.anyio
async def test_supabase_cycle_repository_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "/rpc/" in str(request.url):
            return httpx.Response(200, json=ROW)
        return httpx.Response(200, json=[ROW])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store: Any = SimpleNamespace(base_url="https://example.test", _headers={}, client=client)
        repository = SupabaseCycleRepository(store)
        activated = await repository.activate("v:2026-09-03:cutoff", activated_time())
        fetched = await repository.get("cycle-1")
        latest = await repository.latest()
        assert activated.data_freshness == "cached" and activated.events
        assert fetched is not None and fetched.cycle_id == "cycle-1"
        assert latest is not None and latest.historical


@pytest.mark.anyio
async def test_supabase_cycle_repository_empty_and_invalid_rpc() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store: Any = SimpleNamespace(base_url="https://example.test", _headers={}, client=client)
        repository = SupabaseCycleRepository(store)
        assert await repository.get("missing") is None
        assert await repository.latest() is None
        with pytest.raises(RuntimeError, match="Invalid cycle"):
            await repository.activate("v:date:cutoff", activated_time())


def activated_time() -> datetime:
    return datetime(2026, 9, 3, tzinfo=UTC)
