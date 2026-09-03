from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest, TrailingStopOrderRequest

from app.integrations.broker import (
    AmbiguousBrokerResult,
    BrokerOrderCommand,
    BrokerOrderKind,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
)

_STATUS = {
    "new": BrokerOrderStatus.SUBMITTED,
    "accepted": BrokerOrderStatus.SUBMITTED,
    "pending_new": BrokerOrderStatus.PENDING,
    "partially_filled": BrokerOrderStatus.PARTIALLY_FILLED,
    "filled": BrokerOrderStatus.FILLED,
    "canceled": BrokerOrderStatus.CANCELED,
    "rejected": BrokerOrderStatus.REJECTED,
    "expired": BrokerOrderStatus.EXPIRED,
}


class AlpacaPyBroker:
    """Paper-only alpaca-py adapter. Decimal-to-float conversion occurs only at the SDK edge."""

    def __init__(self, client: TradingClient) -> None:
        if urlsplit(str(client._base_url)).hostname != "paper-api.alpaca.markets":
            raise ValueError("Broker client must use the Alpaca Paper endpoint")
        self.client = client

    @staticmethod
    def _snapshot(order: Any) -> BrokerOrderSnapshot:
        kind = str(order.type).lower().replace("ordertype.", "")
        status = str(order.status).lower().replace("orderstatus.", "")
        side = str(order.side).lower().replace("orderside.", "")
        return BrokerOrderSnapshot(
            broker_order_id=str(order.id),
            client_order_id=str(order.client_order_id),
            symbol=str(order.symbol),
            side=side,
            kind=BrokerOrderKind(kind),
            status=_STATUS.get(status, BrokerOrderStatus.PENDING),
            quantity=Decimal(str(order.qty)),
            filled_quantity=Decimal(str(order.filled_qty or 0)),
            average_fill_price=(
                Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None
            ),
            stop_price=(Decimal(str(order.stop_price)) if order.stop_price else None),
            trail_percent=(Decimal(str(order.trail_percent)) if order.trail_percent else None),
            observed_at=datetime.now(UTC),
        )

    @staticmethod
    def _request(command: BrokerOrderCommand) -> Any:
        common = {
            "symbol": command.symbol,
            "qty": float(command.quantity),
            "side": OrderSide.BUY if command.side == "buy" else OrderSide.SELL,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": command.client_order_id,
        }
        if command.kind == BrokerOrderKind.MARKET:
            return MarketOrderRequest(**common)
        if command.kind == BrokerOrderKind.STOP and command.stop_price is not None:
            return StopOrderRequest(**common, stop_price=float(command.stop_price))
        if command.kind == BrokerOrderKind.TRAILING_STOP and command.trail_percent is not None:
            return TrailingStopOrderRequest(**common, trail_percent=float(command.trail_percent))
        raise ValueError("Invalid broker order command")

    async def submit(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot:
        existing = await self.get_by_client_order_id(command.client_order_id)
        if existing is not None:
            return existing
        try:
            order = await asyncio.to_thread(self.client.submit_order, self._request(command))
        except Exception as error:
            recoverable = isinstance(error, TimeoutError | ConnectionError) or getattr(
                error, "status_code", None
            ) in {409, 422}
            if not recoverable:
                raise
            recovered = await self.get_by_client_order_id(command.client_order_id)
            if recovered is None:
                raise AmbiguousBrokerResult(
                    "Paper order result is ambiguous; reconciliation required"
                ) from error
            return recovered
        return self._snapshot(order)

    async def get_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot | None:
        try:
            order = await asyncio.to_thread(self.client.get_order_by_client_id, client_order_id)
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                return None
            if isinstance(error, TimeoutError | ConnectionError):
                raise AmbiguousBrokerResult("Paper order lookup is ambiguous") from error
            raise
        return self._snapshot(order)

    async def cancel(self, broker_order_id: str) -> None:
        await asyncio.to_thread(self.client.cancel_order_by_id, broker_order_id)
