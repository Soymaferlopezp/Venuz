from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

from app.domain.order_lifecycle import FundamentalSeverity, stable_identifier
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT


def test_order_observation_endpoints_are_read_only_and_sanitized(client: TestClient) -> None:
    cycle_id = client.post("/v1/cycles/activate", json={}).json()["cycle_id"]
    app = cast(Any, client.app)
    assert isinstance(app.state.broker, FakeBroker)
    assert isinstance(app.state.order_repository, MemoryOrderRepository)

    async def arrange() -> None:
        service = OrderLifecycleService(app.state.order_repository, app.state.broker)
        entry = await service.submit_entry(
            cycle_id,
            "ACME",
            Decimal("3"),
            Decimal("110"),
            datetime(2026, 9, 3, 14, 30, tzinfo=UTC),
            preflight=APPROVED_PREFLIGHT,
        )
        app.state.broker.fill(entry.client_order_id, Decimal("3"), Decimal("100"))
        await service.reconcile_order(entry.intent_key, Decimal("110"))
        await service.fundamental_deterioration(
            stable_identifier("position", f"{cycle_id}:ACME"),
            FundamentalSeverity.NONCRITICAL_RED,
            "noncritical_margin_warning",
            ("https://www.sec.gov/example",),
        )

    asyncio.run(arrange())
    orders = client.get(f"/v1/cycles/{cycle_id}/orders")
    approvals = client.get(f"/v1/cycles/{cycle_id}/approvals")
    audit = client.get(f"/v1/cycles/{cycle_id}/audit")
    assert orders.status_code == approvals.status_code == audit.status_code == 200
    assert len(orders.json()) == 2
    assert approvals.json()[0]["status"] == "pending"
    serialized = str((orders.json(), approvals.json(), audit.json())).lower()
    for forbidden in (
        "client_order_id",
        "broker_order_id",
        "intent_key",
        "authorization",
        "secret",
    ):
        assert forbidden not in serialized
    assert client.post(f"/v1/cycles/{cycle_id}/orders", json={}).status_code == 405


def test_empty_observation_endpoints_return_empty_collections(client: TestClient) -> None:
    for suffix in ("orders", "approvals", "audit"):
        assert client.get(f"/v1/cycles/unknown/{suffix}").json() == []
