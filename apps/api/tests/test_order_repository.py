from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.domain.order_lifecycle import (
    ApprovalRecord,
    AuditRecord,
    OrderPurpose,
    OrderRecord,
    PositionRecord,
)
from app.integrations.broker import BrokerOrderKind, BrokerOrderSnapshot, BrokerOrderStatus
from app.repositories.analysis import SupabaseRestStore
from app.repositories.orders import SupabaseOrderRepository

NOW = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
ORDER_ROW: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "cycle_id": "00000000-0000-0000-0000-000000000002",
    "position_id": None,
    "intent_key": "cycle:ACME:entry:v1",
    "client_order_id": "vz-client",
    "broker_order_id": None,
    "symbol": "ACME",
    "purpose": "entry",
    "side": "buy",
    "order_type": "market",
    "status": "pending",
    "quantity": "2",
    "filled_quantity": "0",
    "average_fill_price": None,
    "stop_price": None,
    "trail_percent": None,
    "observed_at": NOW.isoformat(),
}
POSITION_ROW: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000003",
    "cycle_id": ORDER_ROW["cycle_id"],
    "symbol": "ACME",
    "quantity": "2",
    "average_fill_price": "100",
    "estimated_price": "110",
    "protection_mode": "initial",
    "updated_at": NOW.isoformat(),
}
APPROVAL_ROW: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000004",
    "cycle_id": ORDER_ROW["cycle_id"],
    "symbol": "ACME",
    "reason_code": "warning",
    "status": "pending",
    "evidence_links": ["https://www.sec.gov/example"],
    "created_at": NOW.isoformat(),
}
AUDIT_ROW: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000005",
    "cycle_id": ORDER_ROW["cycle_id"],
    "event_type": "order.submitted",
    "symbol": "ACME",
    "decision": "submitted",
    "correlation_id": "00000000-0000-0000-0000-000000000006",
    "sanitized_details": {"detail": "safe"},
    "occurred_at": NOW.isoformat(),
}


def _proposed() -> OrderRecord:
    return OrderRecord(
        order_id=str(ORDER_ROW["id"]),
        cycle_id=str(ORDER_ROW["cycle_id"]),
        intent_key=str(ORDER_ROW["intent_key"]),
        client_order_id=str(ORDER_ROW["client_order_id"]),
        symbol="ACME",
        purpose=OrderPurpose.ENTRY,
        side="buy",
        kind=BrokerOrderKind.MARKET,
        status=BrokerOrderStatus.PENDING,
        quantity=Decimal("2"),
        observed_at=NOW,
    )


@pytest.mark.anyio
async def test_supabase_order_repository_covers_durable_crud_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/rpc/reserve_global_order"):
            return httpx.Response(200, json=ORDER_ROW | {"reservation_created": True})
        if path.endswith("/global_orders") and request.method == "PATCH":
            return httpx.Response(200, json=[ORDER_ROW | body])
        if path.endswith("/global_orders"):
            return httpx.Response(200, json=[ORDER_ROW])
        if path.endswith("/global_positions") and request.method == "POST":
            return httpx.Response(200, json=[POSITION_ROW | body])
        if path.endswith("/global_positions"):
            return httpx.Response(200, json=[POSITION_ROW])
        if path.endswith("/global_approval_requests") and request.method == "POST":
            return httpx.Response(200, json=[APPROVAL_ROW])
        if path.endswith("/global_approval_requests"):
            return httpx.Response(200, json=[APPROVAL_ROW])
        if path.endswith("/global_audit_events") and request.method == "POST":
            return httpx.Response(204)
        if path.endswith("/global_audit_events"):
            return httpx.Response(200, json=[AUDIT_ROW])
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseOrderRepository(
            SupabaseRestStore("https://example.supabase.co", "local-test-key", client)
        )
        reserved, created = await repository.reserve_order(_proposed())
        assert created and reserved.intent_key == ORDER_ROW["intent_key"]
        snapshot = BrokerOrderSnapshot(
            broker_order_id="paper-order",
            client_order_id="vz-client",
            symbol="ACME",
            side="buy",
            kind=BrokerOrderKind.MARKET,
            status=BrokerOrderStatus.PARTIALLY_FILLED,
            quantity=Decimal("2"),
            filled_quantity=Decimal("1"),
            average_fill_price=Decimal("100"),
            observed_at=NOW,
        )
        assert (await repository.apply_snapshot("vz-client", snapshot)).filled_quantity == 1
        assert (
            await repository.mark_ambiguous("vz-client", NOW)
        ).status == BrokerOrderStatus.PENDING
        assert await repository.order_by_intent(str(ORDER_ROW["intent_key"])) is not None
        assert await repository.active_closing_order("position") is not None
        assert await repository.active_entry_order(str(ORDER_ROW["cycle_id"]), "ACME") is not None
        position = PositionRecord(
            position_id=str(POSITION_ROW["id"]),
            cycle_id=str(ORDER_ROW["cycle_id"]),
            symbol="ACME",
            quantity=Decimal("2"),
            average_fill_price=Decimal("100"),
            estimated_price=Decimal("110"),
            updated_at=NOW,
        )
        assert (await repository.save_position(position)).symbol == "ACME"
        assert await repository.position(position.position_id) == position
        approval = ApprovalRecord(
            approval_id=str(APPROVAL_ROW["id"]),
            cycle_id=str(ORDER_ROW["cycle_id"]),
            symbol="ACME",
            reason_code="warning",
            evidence_links=("https://www.sec.gov/example",),
            created_at=NOW,
        )
        assert await repository.save_approval(approval) == approval
        audit = AuditRecord(
            audit_id=str(AUDIT_ROW["id"]),
            cycle_id=str(ORDER_ROW["cycle_id"]),
            event_type="order.submitted",
            symbol="ACME",
            decision="submitted",
            correlation_id=str(AUDIT_ROW["correlation_id"]),
            sanitized_details={"detail": "safe"},
            occurred_at=NOW,
        )
        await repository.save_audit(audit)
        assert len(await repository.cycle_orders(str(ORDER_ROW["cycle_id"]))) == 1
        assert await repository.cycle_approvals(str(ORDER_ROW["cycle_id"])) == (approval,)
        assert await repository.cycle_audit(str(ORDER_ROW["cycle_id"])) == (audit,)
    assert all("local-test-key" not in str(request.url) for request in requests)


@pytest.mark.anyio
async def test_supabase_repository_empty_reads_and_invalid_writes_fail_safe() -> None:
    responses = iter(
        (
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseOrderRepository(
            SupabaseRestStore("https://example.supabase.co", "test", client)
        )
        assert await repository.order_by_intent("missing") is None
        assert await repository.active_closing_order("missing") is None
        assert await repository.position("missing") is None
        with pytest.raises(RuntimeError, match="position"):
            await repository.save_position(
                PositionRecord(
                    position_id="id",
                    cycle_id="cycle",
                    symbol="ACME",
                    quantity=Decimal("1"),
                    average_fill_price=Decimal("1"),
                    updated_at=NOW,
                )
            )
        with pytest.raises(RuntimeError, match="update"):
            await repository.mark_ambiguous("missing", NOW)
