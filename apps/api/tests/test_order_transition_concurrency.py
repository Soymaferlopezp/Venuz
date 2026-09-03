from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.order_lifecycle import stable_identifier
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT


@pytest.mark.anyio
async def test_competing_protection_transitions_cannot_overlap() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle",
        "ACME",
        Decimal("10"),
        Decimal("110"),
        datetime(2026, 9, 3, 14, 30, tzinfo=UTC),
        preflight=APPROVED_PREFLIGHT,
    )
    broker.fill(entry.client_order_id, Decimal("10"), Decimal("100"))
    await service.reconcile_order(entry.intent_key, Decimal("110"))
    position_id = stable_identifier("position", "cycle:ACME")
    outcomes = await asyncio.gather(
        service.observe_price(position_id, Decimal("110")),
        service.observe_price(position_id, Decimal("120")),
        return_exceptions=True,
    )
    assert len(outcomes) == 2
    active = [
        item
        for item in await repository.cycle_orders("cycle")
        if item.side == "sell" and item.status.value in {"pending", "submitted", "partially_filled"}
    ]
    assert len(active) == 1
