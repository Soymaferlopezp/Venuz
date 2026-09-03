from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from app.domain.order_lifecycle import (
    ApprovalRecord,
    AuditRecord,
    FundamentalSeverity,
    OrderPurpose,
    OrderRecord,
    PositionMode,
    PositionRecord,
    ProtectionPlan,
    broker_client_order_id,
    initial_protection,
    protection_for_price,
    stable_identifier,
)
from app.domain.paper_execution import PREFLIGHT_GUARD_CODES, PreflightDecision
from app.integrations.broker import (
    AmbiguousBrokerResult,
    Broker,
    BrokerOrderCommand,
    BrokerOrderKind,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
)
from app.repositories.orders import ACTIVE_ORDER_STATUSES, OrderRepository


class UnsafeOrderTransition(RuntimeError):
    pass


class OrderLifecycleService:
    def __init__(
        self,
        repository: OrderRepository,
        broker: Broker,
        *,
        auto_execution_enabled: bool = False,
    ) -> None:
        self.repository = repository
        self.broker = broker
        self.auto_execution_enabled = auto_execution_enabled

    async def _audit(
        self,
        *,
        cycle_id: str,
        symbol: str,
        event_type: str,
        decision: str,
        detail: str,
        now: datetime,
        discriminator: str,
    ) -> None:
        key = f"{cycle_id}:{symbol}:{event_type}:{discriminator}"
        await self.repository.save_audit(
            AuditRecord(
                audit_id=stable_identifier("audit", key),
                cycle_id=cycle_id,
                event_type=event_type,
                symbol=symbol,
                decision=decision,
                correlation_id=stable_identifier("correlation", f"{cycle_id}:{symbol}"),
                sanitized_details={"detail": detail},
                occurred_at=now,
            )
        )

    @staticmethod
    def _proposed_order(
        *,
        cycle_id: str,
        position_id: str | None,
        symbol: str,
        purpose: OrderPurpose,
        side: Literal["buy", "sell"],
        kind: BrokerOrderKind,
        quantity: Decimal,
        now: datetime,
        discriminator: str,
        stop_price: Decimal | None = None,
        trail_percent: Decimal | None = None,
    ) -> OrderRecord:
        intent = f"{cycle_id}:{symbol}:{purpose.value}:{discriminator}"
        return OrderRecord(
            order_id=stable_identifier("order", intent),
            cycle_id=cycle_id,
            position_id=position_id,
            intent_key=intent,
            client_order_id=broker_client_order_id(intent),
            symbol=symbol.upper(),
            purpose=purpose,
            side=side,
            kind=kind,
            status=BrokerOrderStatus.PENDING,
            quantity=quantity,
            stop_price=stop_price,
            trail_percent=trail_percent,
            observed_at=now,
        )

    async def _submit_reserved(self, proposed: OrderRecord) -> OrderRecord:
        reserved, created = await self.repository.reserve_order(proposed)
        try:
            remote = await self.broker.get_by_client_order_id(reserved.client_order_id)
        except AmbiguousBrokerResult:
            now = datetime.now(UTC)
            await self.repository.mark_ambiguous(reserved.client_order_id, now)
            await self._audit(
                cycle_id=reserved.cycle_id,
                symbol=reserved.symbol,
                event_type="order.lookup_ambiguous",
                decision="reconcile_before_retry",
                detail="Paper broker lookup was ambiguous; submission was not attempted",
                now=now,
                discriminator=reserved.client_order_id,
            )
            raise
        if remote is not None:
            return await self._process_snapshot(reserved, remote)
        if not created and reserved.status not in ACTIVE_ORDER_STATUSES:
            return reserved
        command = BrokerOrderCommand(
            client_order_id=reserved.client_order_id,
            symbol=reserved.symbol,
            side=reserved.side,
            kind=reserved.kind,
            quantity=reserved.quantity,
            stop_price=reserved.stop_price,
            trail_percent=reserved.trail_percent,
        )
        try:
            snapshot = await self.broker.submit(command)
        except AmbiguousBrokerResult:
            try:
                recovered = await self.broker.get_by_client_order_id(reserved.client_order_id)
            except AmbiguousBrokerResult:
                recovered = None
            if recovered is None:
                now = datetime.now(UTC)
                await self.repository.mark_ambiguous(reserved.client_order_id, now)
                await self._audit(
                    cycle_id=reserved.cycle_id,
                    symbol=reserved.symbol,
                    event_type="order.submission_ambiguous",
                    decision="reconcile_before_retry",
                    detail="Paper broker response was ambiguous; no new intent may be created",
                    now=now,
                    discriminator=reserved.client_order_id,
                )
                raise
            snapshot = recovered
        updated = await self._process_snapshot(reserved, snapshot)
        await self._audit(
            cycle_id=updated.cycle_id,
            symbol=updated.symbol,
            event_type="order.submitted",
            decision=updated.status.value,
            detail=f"{updated.purpose.value} accepted by Paper broker",
            now=updated.observed_at,
            discriminator=updated.client_order_id,
        )
        return updated

    async def submit_entry(
        self,
        cycle_id: str,
        symbol: str,
        quantity: Decimal,
        estimated_price: Decimal | None,
        now: datetime | None = None,
        *,
        preflight: PreflightDecision,
    ) -> OrderRecord:
        instant = now or datetime.now(UTC)
        observed_codes = {guard.code for guard in preflight.guards}
        approved = (
            preflight.eligible
            and observed_codes == PREFLIGHT_GUARD_CODES
            and all(guard.passed for guard in preflight.guards)
        )
        if not approved:
            await self._audit(
                cycle_id=cycle_id,
                symbol=symbol.upper(),
                event_type="order.preflight_rejected",
                decision="no_submission",
                detail="A complete current preflight approval is required",
                now=instant,
                discriminator=str(len(preflight.guards)),
            )
            raise UnsafeOrderTransition("Entry submission requires an approved full preflight")
        proposed = self._proposed_order(
            cycle_id=cycle_id,
            position_id=None,
            symbol=symbol.upper(),
            purpose=OrderPurpose.ENTRY,
            side="buy",
            kind=BrokerOrderKind.MARKET,
            quantity=quantity,
            now=instant,
            discriminator="entry-v1",
        )
        order = await self._submit_reserved(proposed)
        if order.filled_quantity > 0 and order.average_fill_price is not None:
            await self._upsert_entry_position(order, estimated_price)
        return order

    async def submit_automatic_entry(
        self,
        cycle_id: str,
        symbol: str,
        quantity: Decimal,
        estimated_price: Decimal | None,
        preflight: PreflightDecision,
        now: datetime | None = None,
    ) -> OrderRecord:
        if not self.auto_execution_enabled:
            raise UnsafeOrderTransition("Automatic execution is disabled")
        return await self.submit_entry(
            cycle_id,
            symbol,
            quantity,
            estimated_price,
            now,
            preflight=preflight,
        )

    async def _upsert_entry_position(
        self, order: OrderRecord, estimated_price: Decimal | None
    ) -> PositionRecord:
        if order.average_fill_price is None:
            raise UnsafeOrderTransition("A positive fill requires an average fill price")
        position_id = stable_identifier("position", f"{order.cycle_id}:{order.symbol}")
        current = await self.repository.position(position_id)
        position = PositionRecord(
            position_id=position_id,
            cycle_id=order.cycle_id,
            symbol=order.symbol,
            quantity=max(
                order.filled_quantity
                - (current.exit_filled_quantity if current is not None else Decimal("0")),
                Decimal("0"),
            ),
            entry_filled_quantity=order.filled_quantity,
            exit_filled_quantity=(
                current.exit_filled_quantity if current is not None else Decimal("0")
            ),
            average_fill_price=order.average_fill_price,
            estimated_price=estimated_price
            if estimated_price is not None
            else (current.estimated_price if current is not None else None),
            mode=current.mode if current is not None else PositionMode.INITIAL,
            updated_at=order.observed_at,
        )
        saved = await self.repository.save_position(position)
        await self._audit(
            cycle_id=order.cycle_id,
            symbol=order.symbol,
            event_type="fill.reconciled",
            decision=order.status.value,
            detail=f"Entry cumulative fill quantity {order.filled_quantity}",
            now=order.observed_at,
            discriminator=f"{order.client_order_id}:{order.filled_quantity}",
        )
        if saved.quantity > 0 and saved.mode == PositionMode.INITIAL:
            await self._replace_protection(saved, initial_protection(saved.average_fill_price))
        return saved

    async def _process_snapshot(
        self, current: OrderRecord, snapshot: BrokerOrderSnapshot
    ) -> OrderRecord:
        previous_filled = current.filled_quantity
        updated = await self.repository.apply_snapshot(current.client_order_id, snapshot)
        if (
            updated.side == "sell"
            and updated.position_id
            and updated.filled_quantity > previous_filled
        ):
            position = await self.repository.position(updated.position_id)
            if position is not None:
                exit_filled = position.exit_filled_quantity + (
                    updated.filled_quantity - previous_filled
                )
                remaining = position.entry_filled_quantity - exit_filled
                mode = PositionMode.CLOSED if remaining <= 0 else position.mode
                await self.repository.save_position(
                    position.model_copy(
                        update={
                            "quantity": max(remaining, Decimal("0")),
                            "exit_filled_quantity": exit_filled,
                            "mode": mode,
                            "updated_at": snapshot.observed_at,
                        }
                    )
                )
                await self._audit(
                    cycle_id=updated.cycle_id,
                    symbol=updated.symbol,
                    event_type="fill.reconciled",
                    decision=updated.status.value,
                    detail=f"Closing cumulative fill quantity {updated.filled_quantity}",
                    now=snapshot.observed_at,
                    discriminator=f"{updated.client_order_id}:{updated.filled_quantity}",
                )
        return updated

    async def reconcile_order(
        self, intent_key: str, estimated_price: Decimal | None = None
    ) -> OrderRecord:
        order = await self.repository.order_by_intent(intent_key)
        if order is None:
            raise KeyError("Unknown order intent")
        try:
            snapshot = await self.broker.get_by_client_order_id(order.client_order_id)
        except AmbiguousBrokerResult:
            now = datetime.now(UTC)
            await self.repository.mark_ambiguous(order.client_order_id, now)
            await self._audit(
                cycle_id=order.cycle_id,
                symbol=order.symbol,
                event_type="order.reconciliation_ambiguous",
                decision="retry_same_client_order_id",
                detail="Paper broker reconciliation lookup was ambiguous",
                now=now,
                discriminator=order.client_order_id,
            )
            raise
        if snapshot is None:
            await self._audit(
                cycle_id=order.cycle_id,
                symbol=order.symbol,
                event_type="order.reconciliation",
                decision="remote_not_found",
                detail="Paper broker has no order for the durable client identifier",
                now=datetime.now(UTC),
                discriminator=f"{order.client_order_id}:not-found",
            )
            return order
        updated = await self._process_snapshot(order, snapshot)
        if updated.purpose == OrderPurpose.ENTRY and updated.filled_quantity > 0:
            await self._upsert_entry_position(updated, estimated_price)
        await self._audit(
            cycle_id=updated.cycle_id,
            symbol=updated.symbol,
            event_type="order.reconciliation",
            decision=updated.status.value,
            detail="Durable order synchronized with Paper broker",
            now=updated.observed_at,
            discriminator=f"{updated.client_order_id}:{updated.status}:{updated.filled_quantity}",
        )
        return updated

    async def reconcile_cycle(self, cycle_id: str) -> tuple[OrderRecord, ...]:
        reconciled: list[OrderRecord] = []
        for order in await self.repository.cycle_orders(cycle_id):
            if order.status in ACTIVE_ORDER_STATUSES:
                reconciled.append(await self.reconcile_order(order.intent_key))
        return tuple(reconciled)

    async def _replace_protection(
        self, position: PositionRecord, plan: ProtectionPlan
    ) -> OrderRecord:
        active = await self.repository.active_closing_order(position.position_id)
        if active is not None:
            same = (
                active.purpose == plan.purpose
                and active.quantity == position.quantity
                and active.stop_price == plan.stop_price
                and active.trail_percent == plan.trail_percent
            )
            if same:
                return active
            if active.broker_order_id is None:
                raise UnsafeOrderTransition("Cannot replace an unreconciled closing order")
            await self.broker.cancel(active.broker_order_id)
            canceled = await self.broker.get_by_client_order_id(active.client_order_id)
            if canceled is None or canceled.status != BrokerOrderStatus.CANCELED:
                raise UnsafeOrderTransition("Closing-order cancellation was not confirmed")
            await self.repository.apply_snapshot(active.client_order_id, canceled)
            await self._audit(
                cycle_id=position.cycle_id,
                symbol=position.symbol,
                event_type="protection.canceled",
                decision="confirmed",
                detail=f"Canceled {active.purpose.value} before replacement",
                now=canceled.observed_at,
                discriminator=active.client_order_id,
            )
        discriminator = ":".join(
            (
                str(position.quantity),
                str(plan.stop_price or "none"),
                str(plan.trail_percent or "none"),
            )
        )
        proposed = self._proposed_order(
            cycle_id=position.cycle_id,
            position_id=position.position_id,
            symbol=position.symbol,
            purpose=plan.purpose,
            side="sell",
            kind=plan.kind,
            quantity=position.quantity,
            now=position.updated_at,
            discriminator=discriminator,
            stop_price=plan.stop_price,
            trail_percent=plan.trail_percent,
        )
        order = await self._submit_reserved(proposed)
        await self.repository.save_position(
            position.model_copy(update={"mode": plan.mode, "updated_at": order.observed_at})
        )
        await self._audit(
            cycle_id=position.cycle_id,
            symbol=position.symbol,
            event_type="protection.activated",
            decision=plan.mode.value,
            detail=plan.reason,
            now=order.observed_at,
            discriminator=order.client_order_id,
        )
        return order

    async def observe_price(self, position_id: str, market_price: Decimal) -> OrderRecord | None:
        position = await self.repository.position(position_id)
        if position is None:
            raise KeyError("Unknown position")
        active_entry = await self.repository.active_entry_order(position.cycle_id, position.symbol)
        if active_entry is not None:
            await self._audit(
                cycle_id=position.cycle_id,
                symbol=position.symbol,
                event_type="protection.transition_deferred",
                decision="partial_entry_active",
                detail="Advanced protection waits until the entry is terminal",
                now=position.updated_at,
                discriminator=f"{active_entry.client_order_id}:{market_price}",
            )
            return None
        plan = protection_for_price(position, market_price)
        if plan is None or position.mode in {
            PositionMode.TRAILING,
            PositionMode.EXITING,
            PositionMode.CLOSED,
        }:
            return None
        return await self._replace_protection(position, plan)

    async def fundamental_deterioration(
        self,
        position_id: str,
        severity: FundamentalSeverity,
        reason_code: str,
        evidence_links: tuple[str, ...],
        now: datetime | None = None,
    ) -> OrderRecord | ApprovalRecord:
        instant = now or datetime.now(UTC)
        position = await self.repository.position(position_id)
        if position is None:
            raise KeyError("Unknown position")
        if severity == FundamentalSeverity.NONCRITICAL_RED:
            key = f"{position.cycle_id}:{position.symbol}:{reason_code}"
            approval = await self.repository.save_approval(
                ApprovalRecord(
                    approval_id=stable_identifier("approval", key),
                    cycle_id=position.cycle_id,
                    symbol=position.symbol,
                    reason_code=reason_code,
                    evidence_links=evidence_links,
                    created_at=instant,
                )
            )
            await self._audit(
                cycle_id=position.cycle_id,
                symbol=position.symbol,
                event_type="fundamentals.noncritical_red",
                decision="approval_requested_nonblocking",
                detail=reason_code,
                now=instant,
                discriminator=approval.approval_id,
            )
            return approval
        active_entry = await self.repository.active_entry_order(position.cycle_id, position.symbol)
        if active_entry is not None:
            if active_entry.broker_order_id is None:
                raise UnsafeOrderTransition("Cannot exit while an entry is unreconciled")
            await self.broker.cancel(active_entry.broker_order_id)
            canceled_entry = await self.broker.get_by_client_order_id(active_entry.client_order_id)
            if canceled_entry is None or canceled_entry.status != BrokerOrderStatus.CANCELED:
                raise UnsafeOrderTransition("Entry-order cancellation was not confirmed")
            await self.repository.apply_snapshot(active_entry.client_order_id, canceled_entry)
            await self._audit(
                cycle_id=position.cycle_id,
                symbol=position.symbol,
                event_type="entry.canceled_for_critical_exit",
                decision="confirmed",
                detail="Canceled remaining entry quantity before critical exit",
                now=canceled_entry.observed_at,
                discriminator=active_entry.client_order_id,
            )
        plan = ProtectionPlan(
            purpose=OrderPurpose.CRITICAL_EXIT,
            kind=BrokerOrderKind.MARKET,
            mode=PositionMode.EXITING,
            reason=f"critical_fundamental_exit:{reason_code}",
        )
        return await self._replace_protection(position, plan)
