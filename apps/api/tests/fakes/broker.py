from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.integrations.broker import (
    AmbiguousBrokerResult,
    BrokerOrderCommand,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
)


class FakeBroker:
    """Mandatory deterministic broker double; it never performs network I/O."""

    def __init__(self) -> None:
        self.orders: dict[str, BrokerOrderSnapshot] = {}
        self.commands: list[BrokerOrderCommand] = []
        self.cancelled: list[str] = []
        self.ambiguous_next_submit = False
        self.persist_ambiguous_submit = False
        self.ambiguous_next_lookup = False
        self._lock = asyncio.Lock()

    async def submit(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot:
        async with self._lock:
            existing = self.orders.get(command.client_order_id)
            if existing is not None:
                return existing
            snapshot = BrokerOrderSnapshot(
                broker_order_id=str(uuid5(NAMESPACE_URL, command.client_order_id)),
                client_order_id=command.client_order_id,
                symbol=command.symbol,
                side=command.side,
                kind=command.kind,
                status=BrokerOrderStatus.SUBMITTED,
                quantity=command.quantity,
                stop_price=command.stop_price,
                trail_percent=command.trail_percent,
                observed_at=datetime.now(UTC),
            )
            self.commands.append(command)
            if self.persist_ambiguous_submit:
                self.orders[command.client_order_id] = snapshot
            if self.ambiguous_next_submit or self.persist_ambiguous_submit:
                self.ambiguous_next_submit = False
                self.persist_ambiguous_submit = False
                raise AmbiguousBrokerResult("Fake ambiguous result")
            self.orders[command.client_order_id] = snapshot
            return snapshot

    async def get_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot | None:
        if self.ambiguous_next_lookup:
            self.ambiguous_next_lookup = False
            raise AmbiguousBrokerResult("Fake ambiguous lookup")
        return self.orders.get(client_order_id)

    async def cancel(self, broker_order_id: str) -> None:
        self.cancelled.append(broker_order_id)
        for key, order in tuple(self.orders.items()):
            if order.broker_order_id == broker_order_id:
                self.orders[key] = order.model_copy(update={"status": BrokerOrderStatus.CANCELED})

    def fill(self, client_order_id: str, quantity: Decimal, average_price: Decimal) -> None:
        order = self.orders[client_order_id]
        status = (
            BrokerOrderStatus.FILLED
            if quantity == order.quantity
            else BrokerOrderStatus.PARTIALLY_FILLED
        )
        self.orders[client_order_id] = order.model_copy(
            update={
                "status": status,
                "filled_quantity": quantity,
                "average_fill_price": average_price,
                "observed_at": datetime.now(UTC),
            }
        )
