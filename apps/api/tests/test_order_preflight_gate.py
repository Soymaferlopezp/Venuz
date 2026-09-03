from decimal import Decimal

import pytest

from app.domain.paper_execution import PreflightDecision
from app.repositories.orders import MemoryOrderRepository
from app.services.orders import OrderLifecycleService, UnsafeOrderTransition
from tests.fakes.broker import FakeBroker
from tests.order_support import APPROVED_PREFLIGHT

REJECTED_PREFLIGHT = PreflightDecision(eligible=False, guards=())
FORGED_INCOMPLETE_PREFLIGHT = PreflightDecision(eligible=True, guards=())


@pytest.mark.anyio
@pytest.mark.parametrize("preflight", [REJECTED_PREFLIGHT, FORGED_INCOMPLETE_PREFLIGHT])
async def test_entry_rejects_failed_or_incomplete_preflight(
    preflight: PreflightDecision,
) -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    service = OrderLifecycleService(repository, broker)
    with pytest.raises(UnsafeOrderTransition, match="preflight"):
        await service.submit_entry("cycle", "ACME", Decimal("1"), None, preflight=preflight)
    assert broker.commands == []
    audit = await repository.cycle_audit("cycle")
    assert audit[0].event_type == "order.preflight_rejected"


@pytest.mark.anyio
async def test_auto_execution_flag_never_bypasses_preflight() -> None:
    repository = MemoryOrderRepository()
    broker = FakeBroker()
    disabled = OrderLifecycleService(repository, broker)
    with pytest.raises(UnsafeOrderTransition, match="disabled"):
        await disabled.submit_automatic_entry(
            "cycle", "ACME", Decimal("1"), None, APPROVED_PREFLIGHT
        )
    enabled = OrderLifecycleService(repository, broker, auto_execution_enabled=True)
    with pytest.raises(UnsafeOrderTransition, match="preflight"):
        await enabled.submit_automatic_entry(
            "cycle", "ACME", Decimal("1"), None, REJECTED_PREFLIGHT
        )
    submitted = await enabled.submit_automatic_entry(
        "cycle", "ACME", Decimal("1"), None, APPROVED_PREFLIGHT
    )
    assert submitted.status.value == "submitted"
    assert len(broker.commands) == 1
