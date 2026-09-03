from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from app.domain.order_lifecycle import ApprovalRecord, AuditRecord, OrderRecord, PositionRecord
from app.integrations.broker import BrokerOrderSnapshot, BrokerOrderStatus
from app.repositories.analysis import SupabaseRestStore

ACTIVE_ORDER_STATUSES = {
    BrokerOrderStatus.PENDING,
    BrokerOrderStatus.SUBMITTED,
    BrokerOrderStatus.PARTIALLY_FILLED,
}


class ActiveClosingOrderConflict(RuntimeError):
    pass


class OrderRepository(Protocol):
    async def reserve_order(self, proposed: OrderRecord) -> tuple[OrderRecord, bool]: ...
    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OrderRecord: ...
    async def mark_ambiguous(self, client_order_id: str, observed_at: datetime) -> OrderRecord: ...
    async def order_by_intent(self, intent_key: str) -> OrderRecord | None: ...
    async def active_closing_order(self, position_id: str) -> OrderRecord | None: ...
    async def active_entry_order(self, cycle_id: str, symbol: str) -> OrderRecord | None: ...
    async def save_position(self, position: PositionRecord) -> PositionRecord: ...
    async def position(self, position_id: str) -> PositionRecord | None: ...
    async def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord: ...
    async def save_audit(self, audit: AuditRecord) -> None: ...
    async def cycle_orders(self, cycle_id: str) -> tuple[OrderRecord, ...]: ...
    async def cycle_approvals(self, cycle_id: str) -> tuple[ApprovalRecord, ...]: ...
    async def cycle_audit(self, cycle_id: str) -> tuple[AuditRecord, ...]: ...


class MemoryOrderRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.orders: dict[str, OrderRecord] = {}
        self.intent_index: dict[str, str] = {}
        self.client_index: dict[str, str] = {}
        self.positions: dict[str, PositionRecord] = {}
        self.approvals: dict[str, ApprovalRecord] = {}
        self.audit_events: dict[str, AuditRecord] = {}

    async def reserve_order(self, proposed: OrderRecord) -> tuple[OrderRecord, bool]:
        async with self._lock:
            existing_id = self.intent_index.get(proposed.intent_key)
            if existing_id is not None:
                return self.orders[existing_id], False
            if proposed.side == "sell" and proposed.position_id is not None:
                conflicting = any(
                    item.position_id == proposed.position_id
                    and item.side == "sell"
                    and item.status in ACTIVE_ORDER_STATUSES
                    for item in self.orders.values()
                )
                if conflicting:
                    raise ActiveClosingOrderConflict(
                        "A different active closing order already protects this position"
                    )
            self.orders[proposed.order_id] = proposed
            self.intent_index[proposed.intent_key] = proposed.order_id
            self.client_index[proposed.client_order_id] = proposed.order_id
            return proposed, True

    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OrderRecord:
        async with self._lock:
            order_id = self.client_index[client_order_id]
            current = self.orders[order_id]
            updated = current.model_copy(
                update={
                    "broker_order_id": snapshot.broker_order_id,
                    "status": snapshot.status,
                    "filled_quantity": snapshot.filled_quantity,
                    "average_fill_price": snapshot.average_fill_price,
                    "stop_price": snapshot.stop_price,
                    "trail_percent": snapshot.trail_percent,
                    "observed_at": snapshot.observed_at,
                }
            )
            self.orders[order_id] = updated
            return updated

    async def mark_ambiguous(self, client_order_id: str, observed_at: datetime) -> OrderRecord:
        async with self._lock:
            order_id = self.client_index[client_order_id]
            current = self.orders[order_id]
            updated = current.model_copy(
                update={"status": BrokerOrderStatus.PENDING, "observed_at": observed_at}
            )
            self.orders[order_id] = updated
            return updated

    async def order_by_intent(self, intent_key: str) -> OrderRecord | None:
        order_id = self.intent_index.get(intent_key)
        return self.orders.get(order_id) if order_id is not None else None

    async def active_closing_order(self, position_id: str) -> OrderRecord | None:
        matches = (
            item
            for item in self.orders.values()
            if item.position_id == position_id
            and item.side == "sell"
            and item.status in ACTIVE_ORDER_STATUSES
        )
        return max(matches, key=lambda item: item.observed_at, default=None)

    async def active_entry_order(self, cycle_id: str, symbol: str) -> OrderRecord | None:
        matches = (
            item
            for item in self.orders.values()
            if item.cycle_id == cycle_id
            and item.symbol == symbol
            and item.side == "buy"
            and item.status in ACTIVE_ORDER_STATUSES
        )
        return max(matches, key=lambda item: item.observed_at, default=None)

    async def save_position(self, position: PositionRecord) -> PositionRecord:
        async with self._lock:
            self.positions[position.position_id] = position
            return position

    async def position(self, position_id: str) -> PositionRecord | None:
        return self.positions.get(position_id)

    async def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        async with self._lock:
            existing = self.approvals.get(approval.approval_id)
            if existing is not None:
                return existing
            self.approvals[approval.approval_id] = approval
            return approval

    async def save_audit(self, audit: AuditRecord) -> None:
        async with self._lock:
            self.audit_events.setdefault(audit.audit_id, audit)

    async def cycle_orders(self, cycle_id: str) -> tuple[OrderRecord, ...]:
        return tuple(item for item in self.orders.values() if item.cycle_id == cycle_id)

    async def cycle_approvals(self, cycle_id: str) -> tuple[ApprovalRecord, ...]:
        return tuple(item for item in self.approvals.values() if item.cycle_id == cycle_id)

    async def cycle_audit(self, cycle_id: str) -> tuple[AuditRecord, ...]:
        return tuple(item for item in self.audit_events.values() if item.cycle_id == cycle_id)


class SupabaseOrderRepository:
    """Backend-only durable global order lifecycle repository."""

    def __init__(self, store: SupabaseRestStore) -> None:
        self.store = store

    async def _request(
        self,
        method: str,
        resource: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: object | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = self.store._headers | ({"Prefer": prefer} if prefer else {})
        safe_payload = json.loads(json.dumps(payload, default=str)) if payload is not None else None
        response = await self.store.client.request(
            method,
            f"{self.store.base_url}/rest/v1/{resource}",
            params=params,
            json=safe_payload,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    @staticmethod
    def _order(row: Mapping[str, Any]) -> OrderRecord:
        return OrderRecord(
            order_id=str(row["id"]),
            cycle_id=str(row["cycle_id"]),
            position_id=str(row["position_id"]) if row.get("position_id") else None,
            intent_key=str(row["intent_key"]),
            client_order_id=str(row["client_order_id"]),
            symbol=str(row["symbol"]),
            purpose=str(row["purpose"]),
            side=str(row["side"]),
            kind=str(row["order_type"]),
            status=str(row["status"]),
            quantity=row["quantity"],
            filled_quantity=row.get("filled_quantity", "0"),
            average_fill_price=row.get("average_fill_price"),
            stop_price=row.get("stop_price"),
            trail_percent=row.get("trail_percent"),
            broker_order_id=str(row["broker_order_id"]) if row.get("broker_order_id") else None,
            observed_at=row["observed_at"],
        )

    async def reserve_order(self, proposed: OrderRecord) -> tuple[OrderRecord, bool]:
        rows = await self._request(
            "POST",
            "rpc/reserve_global_order",
            payload={
                "p_order_id": proposed.order_id,
                "p_cycle_id": proposed.cycle_id,
                "p_position_id": proposed.position_id,
                "p_intent_key": proposed.intent_key,
                "p_client_order_id": proposed.client_order_id,
                "p_symbol": proposed.symbol,
                "p_purpose": proposed.purpose.value,
                "p_side": proposed.side,
                "p_order_type": proposed.kind.value,
                "p_quantity": proposed.quantity,
                "p_stop_price": proposed.stop_price,
                "p_trail_percent": proposed.trail_percent,
                "p_observed_at": proposed.observed_at,
            },
        )
        if not isinstance(rows, Mapping):
            raise RuntimeError("Invalid global order reservation response")
        return self._order(rows), bool(rows["reservation_created"])

    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OrderRecord:
        rows = await self._request(
            "PATCH",
            "global_orders",
            params={"client_order_id": f"eq.{client_order_id}"},
            payload={
                "broker_order_id": snapshot.broker_order_id,
                "status": snapshot.status.value,
                "filled_quantity": snapshot.filled_quantity,
                "average_fill_price": snapshot.average_fill_price,
                "stop_price": snapshot.stop_price,
                "trail_percent": snapshot.trail_percent,
                "observed_at": snapshot.observed_at,
                "updated_at": snapshot.observed_at,
            },
            prefer="return=representation",
        )
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
            raise RuntimeError("Global order update returned no row")
        return self._order(rows[0])

    async def mark_ambiguous(self, client_order_id: str, observed_at: datetime) -> OrderRecord:
        rows = await self._request(
            "PATCH",
            "global_orders",
            params={"client_order_id": f"eq.{client_order_id}"},
            payload={"status": "pending", "observed_at": observed_at, "updated_at": observed_at},
            prefer="return=representation",
        )
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
            raise RuntimeError("Ambiguous order update returned no row")
        return self._order(rows[0])

    async def order_by_intent(self, intent_key: str) -> OrderRecord | None:
        rows = await self._request(
            "GET", "global_orders", params={"intent_key": f"eq.{intent_key}", "limit": "1"}
        )
        return self._order(rows[0]) if isinstance(rows, list) and rows else None

    async def active_closing_order(self, position_id: str) -> OrderRecord | None:
        rows = await self._request(
            "GET",
            "global_orders",
            params={
                "position_id": f"eq.{position_id}",
                "side": "eq.sell",
                "status": "in.(pending,submitted,partially_filled)",
                "order": "observed_at.desc",
                "limit": "1",
            },
        )
        return self._order(rows[0]) if isinstance(rows, list) and rows else None

    async def active_entry_order(self, cycle_id: str, symbol: str) -> OrderRecord | None:
        rows = await self._request(
            "GET",
            "global_orders",
            params={
                "cycle_id": f"eq.{cycle_id}",
                "symbol": f"eq.{symbol}",
                "side": "eq.buy",
                "status": "in.(pending,submitted,partially_filled)",
                "order": "observed_at.desc",
                "limit": "1",
            },
        )
        return self._order(rows[0]) if isinstance(rows, list) and rows else None

    async def save_position(self, position: PositionRecord) -> PositionRecord:
        rows = await self._request(
            "POST",
            "global_positions",
            params={"on_conflict": "id"},
            payload={
                "id": position.position_id,
                "cycle_id": position.cycle_id,
                "symbol": position.symbol,
                "quantity": position.quantity,
                "entry_filled_quantity": position.entry_filled_quantity,
                "exit_filled_quantity": position.exit_filled_quantity,
                "average_fill_price": position.average_fill_price,
                "estimated_price": position.estimated_price,
                "protection_mode": position.mode.value,
                "updated_at": position.updated_at,
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Global position upsert returned no row")
        return self._position(rows[0])

    @staticmethod
    def _position(row: Mapping[str, Any]) -> PositionRecord:
        return PositionRecord(
            position_id=str(row["id"]),
            cycle_id=str(row["cycle_id"]),
            symbol=str(row["symbol"]),
            quantity=row["quantity"],
            entry_filled_quantity=row.get("entry_filled_quantity", "0"),
            exit_filled_quantity=row.get("exit_filled_quantity", "0"),
            average_fill_price=row["average_fill_price"],
            estimated_price=row.get("estimated_price"),
            mode=str(row["protection_mode"]),
            updated_at=row["updated_at"],
        )

    async def position(self, position_id: str) -> PositionRecord | None:
        rows = await self._request(
            "GET", "global_positions", params={"id": f"eq.{position_id}", "limit": "1"}
        )
        return self._position(rows[0]) if isinstance(rows, list) and rows else None

    async def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        rows = await self._request(
            "POST",
            "global_approval_requests",
            params={"on_conflict": "id"},
            payload={
                "id": approval.approval_id,
                "cycle_id": approval.cycle_id,
                "symbol": approval.symbol,
                "reason_code": approval.reason_code,
                "status": approval.status,
                "evidence_links": approval.evidence_links,
                "created_at": approval.created_at,
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if not isinstance(rows, list) or not rows:
            existing = await self._request(
                "GET", "global_approval_requests", params={"id": f"eq.{approval.approval_id}"}
            )
            if not isinstance(existing, list) or not existing:
                raise RuntimeError("Global approval upsert returned no row")
            rows = existing
        row = rows[0]
        return ApprovalRecord(
            approval_id=str(row["id"]),
            cycle_id=str(row["cycle_id"]),
            symbol=str(row["symbol"]),
            reason_code=str(row["reason_code"]),
            status=str(row["status"]),
            evidence_links=tuple(row.get("evidence_links", [])),
            created_at=row["created_at"],
        )

    async def save_audit(self, audit: AuditRecord) -> None:
        await self._request(
            "POST",
            "global_audit_events",
            params={"on_conflict": "id"},
            payload={
                "id": audit.audit_id,
                "cycle_id": audit.cycle_id,
                "event_type": audit.event_type,
                "symbol": audit.symbol,
                "decision": audit.decision,
                "correlation_id": audit.correlation_id,
                "sanitized_details": audit.sanitized_details,
                "occurred_at": audit.occurred_at,
            },
            prefer="resolution=ignore-duplicates",
        )

    async def cycle_orders(self, cycle_id: str) -> tuple[OrderRecord, ...]:
        rows = await self._request(
            "GET", "global_orders", params={"cycle_id": f"eq.{cycle_id}", "order": "observed_at"}
        )
        return tuple(self._order(row) for row in rows)

    async def cycle_approvals(self, cycle_id: str) -> tuple[ApprovalRecord, ...]:
        rows = await self._request(
            "GET", "global_approval_requests", params={"cycle_id": f"eq.{cycle_id}"}
        )
        return tuple(
            ApprovalRecord(
                approval_id=str(row["id"]),
                cycle_id=str(row["cycle_id"]),
                symbol=str(row["symbol"]),
                reason_code=str(row["reason_code"]),
                status=str(row["status"]),
                evidence_links=tuple(row.get("evidence_links", [])),
                created_at=row["created_at"],
            )
            for row in rows
        )

    async def cycle_audit(self, cycle_id: str) -> tuple[AuditRecord, ...]:
        rows = await self._request(
            "GET", "global_audit_events", params={"cycle_id": f"eq.{cycle_id}"}
        )
        return tuple(
            AuditRecord(
                audit_id=str(row["id"]),
                cycle_id=str(row["cycle_id"]),
                event_type=str(row["event_type"]),
                symbol=str(row["symbol"]),
                decision=str(row["decision"]),
                correlation_id=str(row["correlation_id"]),
                sanitized_details=dict(row.get("sanitized_details", {})),
                occurred_at=row["occurred_at"],
            )
            for row in rows
        )
