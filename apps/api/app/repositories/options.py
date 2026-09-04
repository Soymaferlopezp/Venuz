from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.domain.options import OptionEvaluation, OptionPortfolio, OptionsCapability
from app.domain.options_lifecycle import (
    CollateralReservation,
    CollateralStatus,
    OptionCycleSnapshot,
    OptionLifecycleEvent,
    OptionOrderRecord,
    OptionPositionRecord,
    OptionSettlementEvent,
)
from app.domain.order_lifecycle import broker_client_order_id, stable_identifier
from app.integrations.broker import BrokerOrderSnapshot, BrokerOrderStatus
from app.repositories.analysis import SupabaseRestStore

ACTIVE_OPTION_ORDER_STATUSES = {
    BrokerOrderStatus.PENDING,
    BrokerOrderStatus.SUBMITTED,
    BrokerOrderStatus.PARTIALLY_FILLED,
}


class OptionRepository(Protocol):
    async def save_capability(self, capability: OptionsCapability) -> None: ...
    async def reserve_entry(
        self, cycle_id: str, evaluation: OptionEvaluation, portfolio: OptionPortfolio, now: datetime
    ) -> tuple[OptionOrderRecord, bool]: ...
    async def reserve_close(
        self, position: OptionPositionRecord, reason: str, now: datetime
    ) -> tuple[OptionOrderRecord, bool]: ...
    async def order_by_intent(self, intent_key: str) -> OptionOrderRecord | None: ...
    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OptionOrderRecord: ...
    async def active_close(self, position_id: str) -> OptionOrderRecord | None: ...
    async def save_position(self, position: OptionPositionRecord) -> OptionPositionRecord: ...
    async def position(self, position_id: str) -> OptionPositionRecord | None: ...
    async def position_by_contract(
        self, occ_symbol: str, cycle_id: str
    ) -> OptionPositionRecord | None: ...
    async def save_event(self, event: OptionLifecycleEvent) -> None: ...
    async def save_settlement(self, event: OptionSettlementEvent) -> bool: ...
    async def release_collateral(self, intent_key: str, now: datetime) -> None: ...
    async def cycle_snapshot(self, cycle_id: str) -> OptionCycleSnapshot: ...


def _entry_order(cycle_id: str, evaluation: OptionEvaluation, now: datetime) -> OptionOrderRecord:
    candidate = evaluation.candidate
    intent = f"{cycle_id}:option:{candidate.occ_symbol}:sell_to_open:v1"
    return OptionOrderRecord(
        order_id=stable_identifier("option-order", intent),
        cycle_id=cycle_id,
        intent_key=intent,
        client_order_id=broker_client_order_id(intent),
        occ_symbol=candidate.occ_symbol,
        underlying=candidate.underlying,
        position_intent="sell_to_open",
        status=BrokerOrderStatus.PENDING,
        quantity=Decimal("1"),
        observed_at=now,
    )


def _close_order(position: OptionPositionRecord, reason: str, now: datetime) -> OptionOrderRecord:
    intent = f"{position.cycle_id}:option:{position.occ_symbol}:buy_to_close:{reason}:v1"
    return OptionOrderRecord(
        order_id=stable_identifier("option-order", intent),
        cycle_id=position.cycle_id,
        option_position_id=position.position_id,
        intent_key=intent,
        client_order_id=broker_client_order_id(intent),
        occ_symbol=position.occ_symbol,
        underlying=position.underlying,
        position_intent="buy_to_close",
        status=BrokerOrderStatus.PENDING,
        quantity=Decimal(position.contracts),
        observed_at=now,
    )


class MemoryOptionRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.capability_status = "unchecked"
        self.evaluations: dict[str, OptionEvaluation] = {}
        self.orders: dict[str, OptionOrderRecord] = {}
        self.positions: dict[str, OptionPositionRecord] = {}
        self.collateral: dict[str, CollateralReservation] = {}
        self.events: dict[str, OptionLifecycleEvent] = {}
        self.settlements: dict[tuple[str, str], OptionSettlementEvent] = {}
        self.economic_settlements: dict[str, str] = {}
        self.assigned_shares: dict[str, int] = {}
        self.stock_exposures: dict[str, tuple[str, Decimal]] = {}

    async def save_capability(self, capability: OptionsCapability) -> None:
        self.capability_status = capability.status

    async def reserve_entry(
        self, cycle_id: str, evaluation: OptionEvaluation, portfolio: OptionPortfolio, now: datetime
    ) -> tuple[OptionOrderRecord, bool]:
        if not evaluation.eligible:
            raise ValueError("Cannot reserve an ineligible option candidate")
        proposed = _entry_order(cycle_id, evaluation, now)
        candidate = evaluation.candidate
        async with self._lock:
            existing = self.orders.get(proposed.intent_key)
            if existing is not None:
                return existing, False
            if any(
                item.cycle_id == cycle_id and item.position_intent == "sell_to_open"
                for item in self.orders.values()
            ):
                raise ValueError("A cycle can reserve at most one new option trade")

            risk: list[tuple[str, str, Decimal, str]] = [
                (symbol, sector, amount, "stock")
                for symbol, (sector, amount) in self.stock_exposures.items()
            ]
            risk.extend(
                (item.underlying, item.sector, item.amount, "option")
                for item in self.collateral.values()
                if item.status in {CollateralStatus.RESERVED, CollateralStatus.CONSUMED}
            )
            risk.extend(
                (item.underlying, item.sector, item.collateral, "option")
                for item in self.positions.values()
                if item.contracts == 1
                and item.status.value in {"open", "closing"}
                and not any(
                    reservation.cycle_id == item.cycle_id
                    and reservation.occ_symbol == item.occ_symbol
                    and reservation.status in {CollateralStatus.RESERVED, CollateralStatus.CONSUMED}
                    for reservation in self.collateral.values()
                )
            )
            active_option_collateral = sum(
                (amount for _, _, amount, kind in risk if kind == "option"), Decimal("0")
            )
            underlying_exposure = sum(
                (amount for symbol, _, amount, _ in risk if symbol == candidate.underlying),
                Decimal("0"),
            )
            sector_exposure = sum(
                (
                    amount
                    for _, sector, amount, _ in risk
                    if sector.casefold() == candidate.sector.casefold()
                ),
                Decimal("0"),
            )
            sector_companies = {
                symbol
                for symbol, sector, amount, _ in risk
                if amount > 0 and sector.casefold() == candidate.sector.casefold()
            }
            collateral = evaluation.collateral
            if portfolio.options_buying_power < collateral:
                raise ValueError("Options buying power changed before reservation")
            if portfolio.cash - active_option_collateral - collateral < (
                portfolio.equity * Decimal("0.20")
            ):
                raise ValueError("Cash reserve would fall below twenty percent")
            if underlying_exposure + collateral > portfolio.equity * Decimal("0.10"):
                raise ValueError("Underlying assignment exposure would exceed ten percent")
            if sector_exposure + collateral > portfolio.equity * Decimal("0.20"):
                raise ValueError("Sector assignment exposure would exceed twenty percent")
            if len(sector_companies) >= 2 and candidate.underlying not in sector_companies:
                raise ValueError("A third company in the sector is not allowed")

            self.orders[proposed.intent_key] = proposed
            self.evaluations[candidate.occ_symbol] = evaluation
            self.collateral[proposed.intent_key] = CollateralReservation(
                reservation_id=stable_identifier("option-collateral", proposed.intent_key),
                cycle_id=cycle_id,
                intent_key=proposed.intent_key,
                occ_symbol=proposed.occ_symbol,
                underlying=candidate.underlying,
                sector=candidate.sector,
                amount=collateral,
                status=CollateralStatus.RESERVED,
                reserved_at=now,
            )
            return proposed, True

    async def reserve_close(
        self, position: OptionPositionRecord, reason: str, now: datetime
    ) -> tuple[OptionOrderRecord, bool]:
        proposed = _close_order(position, reason, now)
        async with self._lock:
            existing = self.orders.get(proposed.intent_key)
            if existing is not None:
                return existing, False
            if any(
                item.option_position_id == position.position_id
                and item.position_intent == "buy_to_close"
                and item.status in ACTIVE_OPTION_ORDER_STATUSES
                for item in self.orders.values()
            ):
                raise ValueError("An active option close already exists")
            self.orders[proposed.intent_key] = proposed
            return proposed, True

    async def order_by_intent(self, intent_key: str) -> OptionOrderRecord | None:
        return self.orders.get(intent_key)

    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OptionOrderRecord:
        async with self._lock:
            pair = next(
                item for item in self.orders.items() if item[1].client_order_id == client_order_id
            )
            intent, current = pair
            updated = current.model_copy(
                update={
                    "broker_order_id": snapshot.broker_order_id,
                    "status": snapshot.status,
                    "filled_quantity": snapshot.filled_quantity,
                    "average_fill_price": snapshot.average_fill_price,
                    "observed_at": snapshot.observed_at,
                }
            )
            self.orders[intent] = updated
            return updated

    async def active_close(self, position_id: str) -> OptionOrderRecord | None:
        return next(
            (
                item
                for item in self.orders.values()
                if item.option_position_id == position_id
                and item.position_intent == "buy_to_close"
                and item.status in ACTIVE_OPTION_ORDER_STATUSES
            ),
            None,
        )

    async def save_position(self, position: OptionPositionRecord) -> OptionPositionRecord:
        async with self._lock:
            self.positions[position.position_id] = position
            if position.contracts == 1 and position.status.value in {"open", "closing"}:
                for key, reservation in tuple(self.collateral.items()):
                    if (
                        reservation.cycle_id == position.cycle_id
                        and reservation.occ_symbol == position.occ_symbol
                        and reservation.status == CollateralStatus.RESERVED
                    ):
                        self.collateral[key] = reservation.model_copy(
                            update={"status": CollateralStatus.CONSUMED}
                        )
            return position

    async def position(self, position_id: str) -> OptionPositionRecord | None:
        return self.positions.get(position_id)

    async def position_by_contract(
        self, occ_symbol: str, cycle_id: str
    ) -> OptionPositionRecord | None:
        return next(
            (
                item
                for item in self.positions.values()
                if item.occ_symbol == occ_symbol and item.cycle_id == cycle_id
            ),
            None,
        )

    async def save_event(self, event: OptionLifecycleEvent) -> None:
        self.events.setdefault(event.event_id, event)

    async def save_settlement(self, event: OptionSettlementEvent) -> bool:
        async with self._lock:
            position = self.positions.get(event.option_position_id)
            if position is None:
                raise ValueError("Unknown option settlement position")
            if (
                event.cycle_id != position.cycle_id
                or event.occ_symbol != position.occ_symbol
                or event.underlying != position.underlying
                or event.activity_type not in {"OPASN", "OPTRD", "OPEXP"}
                or (event.activity_type in {"OPASN", "OPTRD"} and event.shares != 100)
                or (event.activity_type == "OPEXP" and event.shares != 0)
            ):
                raise ValueError("Option settlement invariant mismatch")
            technical_key = (event.activity_id, event.activity_type)
            existing_event = self.settlements.get(technical_key)
            if existing_event is not None:
                if existing_event != event:
                    raise ValueError("Option settlement technical identity mismatch")
                return False
            event_kind = "expiration" if event.activity_type == "OPEXP" else "assignment"
            existing_kind = self.economic_settlements.get(position.position_id)
            if existing_kind is None:
                if position.contracts != 1 or position.status.value not in {"open", "closing"}:
                    raise ValueError("Option settlement requires one open contract")
                self.economic_settlements[position.position_id] = event_kind
                if event_kind == "assignment":
                    self.assigned_shares[event.underlying] = (
                        self.assigned_shares.get(event.underlying, 0) + event.shares
                    )
                    existing_stock = self.stock_exposures.get(event.underlying)
                    existing_amount = (
                        existing_stock[1] if existing_stock is not None else Decimal("0")
                    )
                    self.stock_exposures[event.underlying] = (
                        position.sector,
                        existing_amount + position.collateral,
                    )
            elif (
                existing_kind != event_kind
                or position.contracts != 0
                or (event_kind == "assignment" and position.status.value != "assigned")
                or (event_kind == "expiration" and position.status.value != "expired")
            ):
                raise ValueError("Option settlement economic identity mismatch")
            self.settlements[technical_key] = event
            return True

    async def release_collateral(self, intent_key: str, now: datetime) -> None:
        current = self.collateral.get(intent_key)
        if current is not None and current.status != CollateralStatus.RELEASED:
            self.collateral[intent_key] = current.model_copy(
                update={"status": CollateralStatus.RELEASED, "released_at": now}
            )

    async def cycle_snapshot(self, cycle_id: str) -> OptionCycleSnapshot:
        evaluations = tuple(
            item
            for item in self.evaluations.values()
            if any(
                order.cycle_id == cycle_id and order.occ_symbol == item.candidate.occ_symbol
                for order in self.orders.values()
            )
        )
        return OptionCycleSnapshot(
            cycle_id=cycle_id,
            capability_status=self.capability_status,
            selected_contract=next(
                (item.candidate.occ_symbol for item in evaluations if item.eligible), None
            ),
            evaluations=evaluations,
            orders=tuple(item for item in self.orders.values() if item.cycle_id == cycle_id),
            positions=tuple(item for item in self.positions.values() if item.cycle_id == cycle_id),
            events=tuple(item for item in self.events.values() if item.cycle_id == cycle_id),
            settlements=tuple(
                item for item in self.settlements.values() if item.cycle_id == cycle_id
            ),
        )


class SupabaseOptionRepository:
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
            headers=headers,
            json=safe_payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    async def save_capability(self, capability: OptionsCapability) -> None:
        await self._request(
            "POST",
            "options_capability_checks",
            payload={
                "status": capability.status,
                "options_approved_level": capability.options_approved_level,
                "options_trading_level": capability.options_trading_level,
                "buying_power_available": capability.options_buying_power_available,
                "paper_endpoint_valid": capability.paper_endpoint_valid,
                "option_assets_available": capability.option_assets_available,
                "contracts_accessible": capability.contracts_accessible,
                "chains_accessible": capability.chains_accessible,
                "snapshots_accessible": capability.snapshots_accessible,
                "feed": capability.feed.value if capability.feed else None,
                "blocking_reasons": capability.blocking_reasons,
                "checked_at": capability.checked_at,
            },
            prefer="return=minimal",
        )

    @staticmethod
    def _order(row: Mapping[str, Any]) -> OptionOrderRecord:
        return OptionOrderRecord(
            order_id=str(row["id"]),
            cycle_id=str(row["cycle_id"]),
            option_position_id=row.get("option_position_id"),
            intent_key=str(row["intent_key"]),
            client_order_id=str(row["client_order_id"]),
            occ_symbol=str(row["symbol"]),
            underlying=str(row["underlying_symbol"]),
            position_intent=str(row["position_intent"]),
            status=str(row["status"]),
            quantity=row["quantity"],
            filled_quantity=row.get("filled_quantity", 0),
            average_fill_price=row.get("average_fill_price"),
            broker_order_id=row.get("broker_order_id"),
            observed_at=row["observed_at"],
        )

    async def reserve_entry(
        self, cycle_id: str, evaluation: OptionEvaluation, portfolio: OptionPortfolio, now: datetime
    ) -> tuple[OptionOrderRecord, bool]:
        proposed = _entry_order(cycle_id, evaluation, now)
        candidate = evaluation.candidate
        row = await self._request(
            "POST",
            "rpc/reserve_option_entry",
            payload={
                "p_order_id": proposed.order_id,
                "p_cycle_id": cycle_id,
                "p_intent_key": proposed.intent_key,
                "p_client_order_id": proposed.client_order_id,
                "p_occ_symbol": candidate.occ_symbol,
                "p_underlying": candidate.underlying,
                "p_sector": candidate.sector,
                "p_expiration": candidate.expiration,
                "p_strike": candidate.strike,
                "p_collateral": evaluation.collateral,
                "p_cash": portfolio.cash,
                "p_equity": portfolio.equity,
                "p_options_buying_power": portfolio.options_buying_power,
                "p_current_position_exposure": portfolio.current_position_assignment_exposure,
                "p_current_sector_exposure": portfolio.current_sector_assignment_exposure,
                "p_sector_company_count": portfolio.sector_company_count,
                "p_evaluation": evaluation.model_dump(mode="json"),
                "p_observed_at": now,
            },
        )
        if not isinstance(row, Mapping):
            raise RuntimeError("Invalid option entry reservation response")
        return self._order(row), bool(row["reservation_created"])

    async def reserve_close(
        self, position: OptionPositionRecord, reason: str, now: datetime
    ) -> tuple[OptionOrderRecord, bool]:
        proposed = _close_order(position, reason, now)
        row = await self._request(
            "POST",
            "rpc/reserve_option_close",
            payload={
                "p_order_id": proposed.order_id,
                "p_position_id": position.position_id,
                "p_intent_key": proposed.intent_key,
                "p_client_order_id": proposed.client_order_id,
                "p_reason": reason,
                "p_observed_at": now,
            },
        )
        if not isinstance(row, Mapping):
            raise RuntimeError("Invalid option close reservation response")
        return self._order(row), bool(row["reservation_created"])

    async def order_by_intent(self, intent_key: str) -> OptionOrderRecord | None:
        rows = await self._request(
            "GET", "global_orders", params={"intent_key": f"eq.{intent_key}", "limit": "1"}
        )
        return self._order(rows[0]) if isinstance(rows, list) and rows else None

    async def apply_snapshot(
        self, client_order_id: str, snapshot: BrokerOrderSnapshot
    ) -> OptionOrderRecord:
        rows = await self._request(
            "PATCH",
            "global_orders",
            params={"client_order_id": f"eq.{client_order_id}"},
            payload={
                "broker_order_id": snapshot.broker_order_id,
                "status": snapshot.status.value,
                "filled_quantity": snapshot.filled_quantity,
                "average_fill_price": snapshot.average_fill_price,
                "observed_at": snapshot.observed_at,
                "updated_at": snapshot.observed_at,
            },
            prefer="return=representation",
        )
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Option order update returned no row")
        return self._order(rows[0])

    async def active_close(self, position_id: str) -> OptionOrderRecord | None:
        rows = await self._request(
            "GET",
            "global_orders",
            params={
                "option_position_id": f"eq.{position_id}",
                "position_intent": "eq.buy_to_close",
                "status": "in.(pending,submitted,partially_filled)",
                "limit": "1",
            },
        )
        return self._order(rows[0]) if isinstance(rows, list) and rows else None

    @staticmethod
    def _position(row: Mapping[str, Any]) -> OptionPositionRecord:
        return OptionPositionRecord(
            position_id=str(row["id"]),
            cycle_id=str(row["cycle_id"]),
            occ_symbol=str(row["occ_symbol"]),
            underlying=str(row["underlying_symbol"]),
            sector=str(row["sector"]),
            contracts=int(row["contracts"]),
            strike=row["strike"],
            expiration=row["expiration"],
            entry_credit_per_share=row["entry_credit_per_share"],
            entry_credit_total=row["entry_credit_total"],
            collateral=row["collateral"],
            status=str(row["status"]),
            opened_at=row["opened_at"],
            updated_at=row["updated_at"],
            closed_at=row.get("closed_at"),
            exit_reason=str(row.get("exit_reason", "none")),
        )

    async def save_position(self, position: OptionPositionRecord) -> OptionPositionRecord:
        rows = await self._request(
            "POST",
            "option_positions",
            params={"on_conflict": "id"},
            payload={
                "id": position.position_id,
                "cycle_id": position.cycle_id,
                "occ_symbol": position.occ_symbol,
                "underlying_symbol": position.underlying,
                "sector": position.sector,
                "contracts": position.contracts,
                "strike": position.strike,
                "expiration": position.expiration,
                "entry_credit_per_share": position.entry_credit_per_share,
                "entry_credit_total": position.entry_credit_total,
                "collateral": position.collateral,
                "status": position.status.value,
                "opened_at": position.opened_at,
                "updated_at": position.updated_at,
                "closed_at": position.closed_at,
                "exit_reason": position.exit_reason.value,
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Option position upsert returned no row")
        return self._position(rows[0])

    async def position(self, position_id: str) -> OptionPositionRecord | None:
        rows = await self._request(
            "GET", "option_positions", params={"id": f"eq.{position_id}", "limit": "1"}
        )
        return self._position(rows[0]) if isinstance(rows, list) and rows else None

    async def position_by_contract(
        self, occ_symbol: str, cycle_id: str
    ) -> OptionPositionRecord | None:
        rows = await self._request(
            "GET",
            "option_positions",
            params={
                "occ_symbol": f"eq.{occ_symbol}",
                "cycle_id": f"eq.{cycle_id}",
                "limit": "1",
            },
        )
        return self._position(rows[0]) if isinstance(rows, list) and rows else None

    async def save_event(self, event: OptionLifecycleEvent) -> None:
        await self._request(
            "POST",
            "option_lifecycle_events",
            params={"on_conflict": "id"},
            payload={
                "id": event.event_id,
                "cycle_id": event.cycle_id,
                "option_position_id": event.option_position_id,
                "event_type": event.event_type,
                "state": event.state,
                "reason": event.reason,
                "sanitized_details": event.sanitized_details,
                "occurred_at": event.occurred_at,
            },
            prefer="resolution=ignore-duplicates",
        )

    async def save_settlement(self, event: OptionSettlementEvent) -> bool:
        rows = await self._request(
            "POST",
            "rpc/record_option_settlement",
            payload={
                "p_activity_id": event.activity_id,
                "p_cycle_id": event.cycle_id,
                "p_position_id": event.option_position_id,
                "p_activity_type": event.activity_type,
                "p_occ_symbol": event.occ_symbol,
                "p_underlying": event.underlying,
                "p_shares": event.shares,
                "p_cash_effect": event.cash_effect,
                "p_occurred_at": event.occurred_at,
            },
        )
        return bool(rows)

    async def release_collateral(self, intent_key: str, now: datetime) -> None:
        await self._request(
            "POST",
            "rpc/release_option_collateral",
            payload={"p_intent_key": intent_key, "p_now": now},
        )

    async def cycle_snapshot(self, cycle_id: str) -> OptionCycleSnapshot:
        rows = await self._request(
            "GET",
            "internal_option_cycle_envelopes",
            params={"cycle_id": f"eq.{cycle_id}", "limit": "1"},
        )
        if not isinstance(rows, list) or not rows:
            return OptionCycleSnapshot(
                cycle_id=cycle_id,
                capability_status="unchecked",
                selected_contract=None,
                evaluations=(),
                orders=(),
                positions=(),
                events=(),
                settlements=(),
            )
        return OptionCycleSnapshot.model_validate(rows[0])
