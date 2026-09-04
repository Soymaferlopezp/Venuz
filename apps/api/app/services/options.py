from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.domain.options import (
    OptionEvaluation,
    OptionExitReason,
    OptionPortfolio,
    OptionsCapability,
    option_exit_reason,
)
from app.domain.options_lifecycle import (
    OptionLifecycleEvent,
    OptionOrderRecord,
    OptionPositionRecord,
    OptionPositionStatus,
    OptionSettlementEvent,
)
from app.domain.order_lifecycle import stable_identifier
from app.integrations.alpaca_options import OptionAccountActivity, OptionsGateway
from app.integrations.broker import (
    AmbiguousBrokerResult,
    Broker,
    BrokerOrderCommand,
    BrokerOrderKind,
    BrokerOrderStatus,
)
from app.repositories.options import OptionRepository


class UnsafeOptionTransition(RuntimeError):
    pass


class OptionsService:
    def __init__(
        self,
        repository: OptionRepository,
        broker: Broker,
        gateway: OptionsGateway,
        *,
        auto_execution_enabled: bool = False,
    ) -> None:
        self.repository = repository
        self.broker = broker
        self.gateway = gateway
        self.auto_execution_enabled = auto_execution_enabled

    async def capability(self) -> OptionsCapability:
        try:
            result = await self.gateway.capability()
        except Exception:
            result = OptionsCapability(
                status="unavailable",
                paper_endpoint_valid=True,
                checked_at=datetime.now(UTC),
                blocking_reasons=("alpaca_options_capability_unavailable",),
            )
        await self.repository.save_capability(result)
        return result

    async def _event(
        self,
        *,
        cycle_id: str,
        position_id: str | None,
        event_type: str,
        state: str,
        reason: str,
        details: dict[str, str],
        now: datetime,
        discriminator: str,
    ) -> None:
        key = f"{cycle_id}:{event_type}:{discriminator}"
        await self.repository.save_event(
            OptionLifecycleEvent(
                event_id=stable_identifier("option-event", key),
                cycle_id=cycle_id,
                option_position_id=position_id,
                event_type=event_type,
                state=state,
                reason=reason,
                sanitized_details=details,
                occurred_at=now,
            )
        )

    async def submit_entry(
        self,
        cycle_id: str,
        evaluation: OptionEvaluation,
        portfolio: OptionPortfolio,
        now: datetime | None = None,
    ) -> OptionOrderRecord:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        if (
            not evaluation.eligible
            or not evaluation.guards
            or not all(item.passed for item in evaluation.guards)
        ):
            raise UnsafeOptionTransition("A complete eligible Options preflight is required")
        order, created = await self.repository.reserve_entry(
            cycle_id, evaluation, portfolio, instant
        )
        return await self._submit_reserved(order, created, evaluation)

    async def submit_automatic_entry(
        self,
        cycle_id: str,
        evaluation: OptionEvaluation,
        portfolio: OptionPortfolio,
        now: datetime | None = None,
    ) -> OptionOrderRecord:
        if not self.auto_execution_enabled:
            raise UnsafeOptionTransition("Automatic Options execution is disabled")
        return await self.submit_entry(cycle_id, evaluation, portfolio, now)

    async def _submit_reserved(
        self,
        order: OptionOrderRecord,
        created: bool,
        evaluation: OptionEvaluation | None = None,
    ) -> OptionOrderRecord:
        try:
            remote = await self.broker.get_by_client_order_id(order.client_order_id)
        except AmbiguousBrokerResult:
            await self._event(
                cycle_id=order.cycle_id,
                position_id=order.option_position_id,
                event_type="option.order.lookup_ambiguous",
                state="pending_reconciliation",
                reason="same_client_order_id_required",
                details={"position_intent": order.position_intent},
                now=datetime.now(UTC),
                discriminator=order.client_order_id,
            )
            raise
        if remote is None and (
            created
            or order.status
            in {
                BrokerOrderStatus.PENDING,
                BrokerOrderStatus.SUBMITTED,
                BrokerOrderStatus.PARTIALLY_FILLED,
            }
        ):
            command = BrokerOrderCommand(
                client_order_id=order.client_order_id,
                symbol=order.occ_symbol,
                side="sell" if order.position_intent == "sell_to_open" else "buy",
                kind=BrokerOrderKind.MARKET,
                quantity=Decimal("1"),
                asset_class="option",
                position_intent=order.position_intent,
            )
            try:
                remote = await self.broker.submit(command)
            except AmbiguousBrokerResult:
                remote = await self.broker.get_by_client_order_id(order.client_order_id)
                if remote is None:
                    await self._event(
                        cycle_id=order.cycle_id,
                        position_id=order.option_position_id,
                        event_type="option.order.submission_ambiguous",
                        state="pending_reconciliation",
                        reason="never_create_second_contract",
                        details={"position_intent": order.position_intent},
                        now=datetime.now(UTC),
                        discriminator=order.client_order_id,
                    )
                    raise
        if remote is None:
            return order
        updated = await self.repository.apply_snapshot(order.client_order_id, remote)
        await self._event(
            cycle_id=updated.cycle_id,
            position_id=updated.option_position_id,
            event_type="option.order.reconciled",
            state=updated.status.value,
            reason=updated.position_intent,
            details={"filled_contracts": str(updated.filled_quantity)},
            now=updated.observed_at,
            discriminator=f"{updated.client_order_id}:{updated.status}:{updated.filled_quantity}",
        )
        if updated.position_intent == "sell_to_open" and evaluation is not None:
            await self._open_after_fill(updated, evaluation)
        elif updated.position_intent == "buy_to_close":
            await self._close_after_fill(updated)
        return updated

    async def _open_after_fill(
        self, order: OptionOrderRecord, evaluation: OptionEvaluation
    ) -> OptionPositionRecord | None:
        if order.filled_quantity < Decimal("1"):
            return None
        if order.average_fill_price is None or order.average_fill_price <= 0:
            raise UnsafeOptionTransition("A filled option requires a positive Paper fill price")
        candidate = evaluation.candidate
        position_id = stable_identifier("option-position", candidate.occ_symbol)
        position = OptionPositionRecord(
            position_id=position_id,
            cycle_id=order.cycle_id,
            occ_symbol=candidate.occ_symbol,
            underlying=candidate.underlying,
            sector=candidate.sector,
            contracts=1,
            strike=candidate.strike,
            expiration=candidate.expiration,
            entry_credit_per_share=order.average_fill_price,
            entry_credit_total=(order.average_fill_price * Decimal("100")).quantize(
                Decimal("0.01")
            ),
            collateral=evaluation.collateral,
            status=OptionPositionStatus.OPEN,
            opened_at=order.observed_at,
            updated_at=order.observed_at,
        )
        saved = await self.repository.save_position(position)
        await self._event(
            cycle_id=order.cycle_id,
            position_id=position_id,
            event_type="option.position.opened",
            state="open",
            reason="reconciled_full_paper_fill",
            details={
                "credit_per_share": str(saved.entry_credit_per_share),
                "credit_total": str(saved.entry_credit_total),
                "collateral": str(saved.collateral),
                "feed": evaluation.candidate.feed.value if evaluation.candidate.feed else "unknown",
            },
            now=order.observed_at,
            discriminator=order.client_order_id,
        )
        return saved

    async def reconcile_entry(
        self, intent_key: str, evaluation: OptionEvaluation
    ) -> OptionOrderRecord:
        order = await self.repository.order_by_intent(intent_key)
        if order is None:
            raise KeyError("Unknown option order intent")
        return await self._submit_reserved(order, False, evaluation)

    async def close_if_required(
        self,
        position_id: str,
        buyback_price: Decimal,
        dte: int,
        *,
        critical_deterioration: bool = False,
        account_risk: bool = False,
        now: datetime | None = None,
    ) -> OptionOrderRecord | None:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        position = await self.repository.position(position_id)
        if position is None:
            raise KeyError("Unknown option position")
        reason = option_exit_reason(
            entry_credit=position.entry_credit_per_share,
            buyback_price=buyback_price,
            dte=dte,
            critical_deterioration=critical_deterioration,
            account_risk=account_risk,
        )
        if reason == OptionExitReason.NONE:
            return None
        active = await self.repository.active_close(position_id)
        desired_suffix = f":{reason.value}:v1"
        if active is not None:
            if active.intent_key.endswith(desired_suffix):
                return await self._submit_reserved(active, False)
            if active.broker_order_id is None:
                raise UnsafeOptionTransition("Cannot replace an unreconciled option close")
            await self.broker.cancel(active.broker_order_id)
            canceled = await self.broker.get_by_client_order_id(active.client_order_id)
            if canceled is None or canceled.status != BrokerOrderStatus.CANCELED:
                raise UnsafeOptionTransition("Option close cancellation was not confirmed")
            await self.repository.apply_snapshot(active.client_order_id, canceled)
        order, created = await self.repository.reserve_close(position, reason.value, instant)
        return await self._submit_reserved(order, created)

    async def _close_after_fill(self, order: OptionOrderRecord) -> None:
        if order.filled_quantity < Decimal("1") or order.option_position_id is None:
            return
        position = await self.repository.position(order.option_position_id)
        if position is None:
            return
        reason = order.intent_key.rsplit(":", 2)[-2]
        updated = position.model_copy(
            update={
                "contracts": 0,
                "status": OptionPositionStatus.CLOSED,
                "closed_at": order.observed_at,
                "updated_at": order.observed_at,
                "exit_reason": OptionExitReason(reason),
            }
        )
        await self.repository.save_position(updated)
        entry_intent = f"{position.cycle_id}:option:{position.occ_symbol}:sell_to_open:v1"
        await self.repository.release_collateral(entry_intent, order.observed_at)

    async def process_activity(
        self, cycle_id: str, activity: OptionAccountActivity
    ) -> OptionSettlementEvent | None:
        if activity.symbol is None:
            return None
        if activity.activity_type not in {"OPASN", "OPTRD", "OPEXP"}:
            raise UnsafeOptionTransition("Unsupported Alpaca option settlement activity")
        position = await self.repository.position_by_contract(activity.symbol, cycle_id)
        if position is None:
            return None
        if position.cycle_id != cycle_id:
            raise UnsafeOptionTransition("Option settlement cycle does not match the position")
        if activity.underlying is not None and activity.underlying != position.underlying:
            raise UnsafeOptionTransition("Option settlement underlying does not match the position")
        if activity.quantity is not None and activity.quantity != Decimal("1"):
            raise UnsafeOptionTransition("Option settlement must reference exactly one contract")
        shares = 100 if activity.activity_type in {"OPASN", "OPTRD"} else 0
        event = OptionSettlementEvent(
            activity_id=activity.activity_id,
            cycle_id=cycle_id,
            option_position_id=position.position_id,
            activity_type=activity.activity_type,
            occ_symbol=position.occ_symbol,
            underlying=position.underlying,
            shares=shares,
            cash_effect=activity.price,
            occurred_at=activity.occurred_at,
        )
        if not await self.repository.save_settlement(event):
            return None
        if activity.activity_type in {"OPASN", "OPTRD"}:
            status = OptionPositionStatus.ASSIGNED
            reason = "alpaca_assignment_or_linked_option_trade"
        else:
            status = OptionPositionStatus.EXPIRED
            reason = "alpaca_otm_expiration"
        await self.repository.save_position(
            position.model_copy(
                update={
                    "contracts": 0,
                    "status": status,
                    "closed_at": activity.occurred_at,
                    "updated_at": activity.occurred_at,
                }
            )
        )
        entry_intent = f"{position.cycle_id}:option:{position.occ_symbol}:sell_to_open:v1"
        await self.repository.release_collateral(entry_intent, activity.occurred_at)
        await self._event(
            cycle_id=cycle_id,
            position_id=position.position_id,
            event_type=f"option.activity.{activity.activity_type.lower()}",
            state=status.value,
            reason=reason,
            details={"underlying_shares": str(shares)},
            now=activity.occurred_at,
            discriminator=activity.activity_id,
        )
        return event

    async def reconcile_after_restart(
        self, cycle_id: str, after: datetime
    ) -> tuple[OptionSettlementEvent, ...]:
        await self.gateway.option_positions()
        processed: list[OptionSettlementEvent] = []
        for activity in await self.gateway.option_activities(after):
            event = await self.process_activity(cycle_id, activity)
            if event is not None:
                processed.append(event)
        return tuple(processed)
