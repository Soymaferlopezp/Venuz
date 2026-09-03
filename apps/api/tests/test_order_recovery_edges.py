from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.integrations.broker import AmbiguousBrokerResult, BrokerOrderStatus
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT


@pytest.mark.anyio
async def test_lookup_timeout_is_audited_and_never_submits_a_second_intent() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    now = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    broker.ambiguous_next_lookup = True
    with pytest.raises(AmbiguousBrokerResult):
        await service.submit_entry(
            "cycle", "ACME", Decimal("1"), None, now, preflight=APPROVED_PREFLIGHT
        )
    assert broker.commands == []
    order = (await repository.cycle_orders("cycle"))[0]
    assert order.status == BrokerOrderStatus.PENDING
    assert (await repository.cycle_audit("cycle"))[0].event_type == "order.lookup_ambiguous"


@pytest.mark.anyio
async def test_restart_reconciliation_handles_ambiguous_and_remote_not_found() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle", "ACME", Decimal("1"), None, preflight=APPROVED_PREFLIGHT
    )
    broker.ambiguous_next_lookup = True
    with pytest.raises(AmbiguousBrokerResult):
        await service.reconcile_order(entry.intent_key)
    del broker.orders[entry.client_order_id]
    unchanged = await service.reconcile_order(entry.intent_key)
    assert unchanged.status == BrokerOrderStatus.PENDING
    event_types = {item.event_type for item in await repository.cycle_audit("cycle")}
    assert "order.reconciliation_ambiguous" in event_types
    assert "order.reconciliation" in event_types
