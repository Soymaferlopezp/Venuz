from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.order_lifecycle import (
    FundamentalSeverity,
    OrderPurpose,
    OrderRecord,
    PositionMode,
)
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT

NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


@pytest.mark.anyio
async def test_critical_exit_cancels_remaining_partial_entry_before_sell() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle", "ACME", Decimal("10"), None, NOW, preflight=APPROVED_PREFLIGHT
    )
    broker.fill(entry.client_order_id, Decimal("4"), Decimal("100"))
    await service.reconcile_order(entry.intent_key)
    position = next(iter(repository.positions.values()))
    exit_order = await service.fundamental_deterioration(
        position.position_id,
        FundamentalSeverity.CRITICAL,
        "negative_latest_net_income",
        ("https://www.sec.gov/example",),
        NOW,
    )
    assert isinstance(exit_order, OrderRecord)
    assert exit_order.purpose == OrderPurpose.CRITICAL_EXIT
    assert exit_order.quantity == Decimal("4")
    assert len(broker.cancelled) == 2
    assert broker.orders[entry.client_order_id].status.value == "canceled"


@pytest.mark.anyio
async def test_late_entry_reconciliation_never_rolls_trailing_back_to_initial() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle", "ACME", Decimal("10"), None, NOW, preflight=APPROVED_PREFLIGHT
    )
    broker.fill(entry.client_order_id, Decimal("10"), Decimal("100"))
    await service.reconcile_order(entry.intent_key)
    position = next(iter(repository.positions.values()))
    await service.observe_price(position.position_id, Decimal("120"))
    commands_before = len(broker.commands)
    await service.reconcile_order(entry.intent_key)
    active = await repository.active_closing_order(position.position_id)
    current = await repository.position(position.position_id)
    assert active is not None and active.purpose == OrderPurpose.TRAILING_STOP
    assert current is not None and current.mode == PositionMode.TRAILING
    assert len(broker.commands) == commands_before
