from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.order_lifecycle import (
    FundamentalSeverity,
    OrderPurpose,
    OrderRecord,
    PositionMode,
    PositionRecord,
    broker_client_order_id,
    initial_protection,
    protection_for_price,
    stable_identifier,
)
from app.integrations.broker import AmbiguousBrokerResult, BrokerOrderKind, BrokerOrderStatus
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService, UnsafeOrderTransition
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT

NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


def test_protection_domain_uses_actual_fill_and_branch_precedence() -> None:
    initial = initial_protection(Decimal("100"))
    assert initial.stop_price == Decimal("90.00")
    assert len(broker_client_order_id("same")) <= 48
    assert stable_identifier("x", "same") == stable_identifier("x", "same")
    position = PositionRecord(
        position_id="position",
        cycle_id="cycle",
        symbol="ACME",
        quantity=Decimal("10"),
        average_fill_price=Decimal("100"),
        estimated_price=Decimal("110"),
        updated_at=NOW,
    )
    assert protection_for_price(position, Decimal("109")) is None
    estimated = protection_for_price(position, Decimal("110"))
    assert estimated is not None and estimated.stop_price == Decimal("104.50")
    trailing = protection_for_price(position, Decimal("115.50"))
    assert trailing is not None and trailing.trail_percent == Decimal("5")
    waiting = position.model_copy(update={"mode": PositionMode.ESTIMATED_PRICE})
    assert protection_for_price(waiting, Decimal("114")) is None
    objective_first = position.model_copy(update={"estimated_price": Decimal("130")})
    plan = protection_for_price(objective_first, Decimal("120"))
    assert plan is not None and plan.reason.startswith("plus_2r")


@pytest.mark.anyio
async def test_concurrent_entry_is_durable_and_fake_broker_is_idempotent() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    first, second = await asyncio.gather(
        service.submit_entry(
            "cycle", "acme", Decimal("10"), Decimal("130"), NOW, preflight=APPROVED_PREFLIGHT
        ),
        service.submit_entry(
            "cycle", "ACME", Decimal("10"), Decimal("130"), NOW, preflight=APPROVED_PREFLIGHT
        ),
    )
    assert first.order_id == second.order_id
    assert len(broker.commands) == 1
    assert all(command.kind == BrokerOrderKind.MARKET for command in broker.commands)


async def _filled_position(
    *, estimated_price: Decimal = Decimal("130"), quantity: Decimal = Decimal("10")
) -> tuple[OrderLifecycleService, MemoryOrderRepository, FakeBroker, str, str]:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle", "ACME", quantity, estimated_price, NOW, preflight=APPROVED_PREFLIGHT
    )
    broker.fill(entry.client_order_id, quantity, Decimal("100"))
    await service.reconcile_order(entry.intent_key, estimated_price)
    position_id = stable_identifier("position", "cycle:ACME")
    return service, repository, broker, position_id, entry.intent_key


@pytest.mark.anyio
async def test_partial_and_full_fills_resize_initial_stop_after_restart() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    first_process = OrderLifecycleService(repository, broker)
    entry = await first_process.submit_entry(
        "cycle", "ACME", Decimal("10"), Decimal("130"), NOW, preflight=APPROVED_PREFLIGHT
    )
    broker.fill(entry.client_order_id, Decimal("4"), Decimal("101"))
    restarted = OrderLifecycleService(repository, broker)
    partial = await restarted.reconcile_order(entry.intent_key, Decimal("130"))
    assert partial.status == BrokerOrderStatus.PARTIALLY_FILLED
    assert broker.commands[-1].quantity == Decimal("4")
    assert broker.commands[-1].stop_price == Decimal("90.90")
    position_id = stable_identifier("position", "cycle:ACME")
    assert await restarted.observe_price(position_id, Decimal("130")) is None
    broker.fill(entry.client_order_id, Decimal("10"), Decimal("102"))
    complete = await restarted.reconcile_order(entry.intent_key, Decimal("130"))
    assert complete.status == BrokerOrderStatus.FILLED
    assert broker.commands[-1].quantity == Decimal("10")
    assert broker.commands[-1].stop_price == Decimal("91.80")
    assert len(broker.cancelled) == 1
    assert len(await restarted.reconcile_cycle("cycle")) == 1


@pytest.mark.anyio
async def test_plus_2r_keeps_full_position_and_activates_trailing_stop() -> None:
    service, repository, broker, position_id, _ = await _filled_position()
    trailing = await service.observe_price(position_id, Decimal("120"))
    assert trailing is not None
    assert trailing.purpose == OrderPurpose.TRAILING_STOP
    assert trailing.quantity == Decimal("10")
    assert trailing.trail_percent == Decimal("5")
    assert len(broker.cancelled) == 1
    position = await repository.position(position_id)
    assert position is not None and position.mode == PositionMode.TRAILING
    assert await service.observe_price(position_id, Decimal("125")) is None


@pytest.mark.anyio
async def test_estimated_price_branch_replaces_each_protection_without_overlap() -> None:
    service, repository, broker, position_id, _ = await _filled_position(
        estimated_price=Decimal("110")
    )
    fair_stop = await service.observe_price(position_id, Decimal("110"))
    assert fair_stop is not None and fair_stop.stop_price == Decimal("104.50")
    assert len(broker.cancelled) == 1
    trailing = await service.observe_price(position_id, Decimal("115.50"))
    assert trailing is not None and trailing.kind == BrokerOrderKind.TRAILING_STOP
    assert len(broker.cancelled) == 2
    active = await repository.active_closing_order(position_id)
    assert active == trailing


@pytest.mark.anyio
async def test_critical_exit_and_noncritical_approval_are_independent() -> None:
    service, repository, broker, position_id, _ = await _filled_position()
    approval = await service.fundamental_deterioration(
        position_id,
        FundamentalSeverity.NONCRITICAL_RED,
        "margin_warning",
        ("https://www.sec.gov/example",),
        NOW,
    )
    duplicate = await service.fundamental_deterioration(
        position_id,
        FundamentalSeverity.NONCRITICAL_RED,
        "margin_warning",
        ("https://www.sec.gov/example",),
        NOW,
    )
    assert approval == duplicate
    unrelated = await service.submit_entry(
        "other-cycle", "NEXT", Decimal("1"), Decimal("20"), NOW, preflight=APPROVED_PREFLIGHT
    )
    assert unrelated.status == BrokerOrderStatus.SUBMITTED
    exit_order = await service.fundamental_deterioration(
        position_id,
        FundamentalSeverity.CRITICAL,
        "negative_latest_free_cash_flow",
        ("https://www.sec.gov/example",),
        NOW,
    )
    assert isinstance(exit_order, OrderRecord)
    assert exit_order.kind == BrokerOrderKind.MARKET and exit_order.side == "sell"
    broker.fill(exit_order.client_order_id, Decimal("4"), Decimal("95"))
    await service.reconcile_order(exit_order.intent_key)
    position = await repository.position(position_id)
    assert position is not None and position.quantity == Decimal("6")
    broker.fill(exit_order.client_order_id, Decimal("10"), Decimal("94"))
    await service.reconcile_order(exit_order.intent_key)
    position = await repository.position(position_id)
    assert position is not None and position.quantity == 0 and position.mode == PositionMode.CLOSED
    assert len(await repository.cycle_approvals("cycle")) == 1
    assert any(
        item.event_type.startswith("fundamentals") for item in await repository.cycle_audit("cycle")
    )


@pytest.mark.anyio
async def test_ambiguous_submission_recovers_or_stays_pending_for_reconciliation() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    broker.persist_ambiguous_submit = True
    recovered = await service.submit_entry(
        "cycle", "ACME", Decimal("2"), None, NOW, preflight=APPROVED_PREFLIGHT
    )
    assert recovered.status == BrokerOrderStatus.SUBMITTED
    broker.ambiguous_next_submit = True
    with pytest.raises(AmbiguousBrokerResult):
        await service.submit_entry(
            "cycle", "NEXT", Decimal("2"), None, NOW, preflight=APPROVED_PREFLIGHT
        )
    pending = await repository.cycle_orders("cycle")
    assert any(
        item.symbol == "NEXT" and item.status == BrokerOrderStatus.PENDING for item in pending
    )
    assert len([item for item in broker.commands if item.symbol == "NEXT"]) == 1


class _NoCancelBroker(FakeBroker):
    async def cancel(self, broker_order_id: str) -> None:
        self.cancelled.append(broker_order_id)


@pytest.mark.anyio
async def test_unconfirmed_cancel_fails_safe_without_overlapping_close() -> None:
    repository = MemoryOrderRepository()
    broker = _NoCancelBroker()
    service = OrderLifecycleService(repository, broker)
    entry = await service.submit_entry(
        "cycle", "ACME", Decimal("10"), Decimal("130"), NOW, preflight=APPROVED_PREFLIGHT
    )
    broker.fill(entry.client_order_id, Decimal("10"), Decimal("100"))
    await service.reconcile_order(entry.intent_key, Decimal("130"))
    position_id = stable_identifier("position", "cycle:ACME")
    with pytest.raises(UnsafeOrderTransition):
        await service.observe_price(position_id, Decimal("120"))
    assert len([item for item in broker.commands if item.side == "sell"]) == 1


@pytest.mark.anyio
async def test_unknown_reconciliation_and_position_fail_explicitly() -> None:
    service = OrderLifecycleService(MemoryOrderRepository(), FakeBroker())
    with pytest.raises(KeyError):
        await service.reconcile_order("missing")
    with pytest.raises(KeyError):
        await service.observe_price("missing", Decimal("1"))
    with pytest.raises(KeyError):
        await service.fundamental_deterioration(
            "missing", FundamentalSeverity.CRITICAL, "reason", (), NOW
        )
