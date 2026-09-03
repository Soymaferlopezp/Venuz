from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from alpaca.trading.enums import OrderSide, OrderStatus, OrderType
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest, TrailingStopOrderRequest

from app.integrations.alpaca_broker import AlpacaPyBroker
from app.integrations.broker import (
    AmbiguousBrokerResult,
    BrokerOrderCommand,
    BrokerOrderKind,
    BrokerOrderStatus,
)


def _order(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": "paper-order",
        "client_order_id": "vz-client",
        "symbol": "ACME",
        "side": OrderSide.BUY,
        "type": OrderType.MARKET,
        "status": OrderStatus.NEW,
        "qty": "2",
        "filled_qty": "0",
        "filled_avg_price": None,
        "stop_price": None,
        "trail_percent": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _NotFound(Exception):
    status_code = 404


class _Conflict(Exception):
    status_code = 409


class _SdkClient:
    _base_url = "https://paper-api.alpaca.markets"

    def __init__(self) -> None:
        self.orders: dict[str, SimpleNamespace] = {}
        self.requests: list[object] = []
        self.cancelled: list[str] = []
        self.timeout_submit = False
        self.persist_timeout = False
        self.persist_conflict = False
        self.timeout_lookup = False

    def get_order_by_client_id(self, client_id: str) -> SimpleNamespace:
        if self.timeout_lookup:
            self.timeout_lookup = False
            raise TimeoutError
        if client_id not in self.orders:
            raise _NotFound
        return self.orders[client_id]

    def submit_order(self, request: object) -> SimpleNamespace:
        self.requests.append(request)
        client_id = str(cast(Any, request).client_order_id)
        order = _order(
            client_order_id=client_id,
            type=cast(Any, request).type,
            side=cast(Any, request).side,
            qty=str(cast(Any, request).qty),
            stop_price=getattr(request, "stop_price", None),
            trail_percent=getattr(request, "trail_percent", None),
        )
        if self.persist_timeout or self.persist_conflict:
            self.orders[client_id] = order
        if self.persist_conflict:
            self.persist_conflict = False
            raise _Conflict
        if self.timeout_submit or self.persist_timeout:
            self.timeout_submit = False
            self.persist_timeout = False
            raise TimeoutError
        self.orders[client_id] = order
        return order

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)


def _broker(client: _SdkClient) -> AlpacaPyBroker:
    return AlpacaPyBroker(cast(Any, client))


def _command(
    kind: BrokerOrderKind = BrokerOrderKind.MARKET,
    *,
    stop: Decimal | None = None,
    trail: Decimal | None = None,
) -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id=f"vz-{kind.value}",
        symbol="ACME",
        side="buy" if kind == BrokerOrderKind.MARKET else "sell",
        kind=kind,
        quantity=Decimal("2"),
        stop_price=stop,
        trail_percent=trail,
    )


@pytest.mark.anyio
async def test_alpaca_adapter_maps_requests_snapshots_and_cancel() -> None:
    client = _SdkClient()
    broker = _broker(client)
    market = await broker.submit(_command())
    stop = await broker.submit(_command(BrokerOrderKind.STOP, stop=Decimal("90.25")))
    trailing = await broker.submit(_command(BrokerOrderKind.TRAILING_STOP, trail=Decimal("5")))
    assert market.kind == BrokerOrderKind.MARKET
    assert market.status == BrokerOrderStatus.SUBMITTED
    assert isinstance(client.requests[0], MarketOrderRequest)
    assert isinstance(client.requests[1], StopOrderRequest)
    assert isinstance(client.requests[2], TrailingStopOrderRequest)
    assert stop.stop_price == Decimal("90.25")
    assert trailing.trail_percent == Decimal("5")
    looked_up = await broker.get_by_client_order_id(market.client_order_id)
    assert looked_up is not None and looked_up.broker_order_id == market.broker_order_id
    await broker.cancel("paper-order")
    assert client.cancelled == ["paper-order"]


@pytest.mark.anyio
async def test_alpaca_adapter_is_idempotent_and_recovers_ambiguous_submit() -> None:
    client = _SdkClient()
    broker = _broker(client)
    command = _command()
    first = await broker.submit(command)
    second = await broker.submit(command)
    assert first.broker_order_id == second.broker_order_id and len(client.requests) == 1
    recoverable = _command(BrokerOrderKind.STOP, stop=Decimal("90"))
    client.persist_timeout = True
    assert (await broker.submit(recoverable)).client_order_id == recoverable.client_order_id
    conflict = _command(BrokerOrderKind.TRAILING_STOP, trail=Decimal("5"))
    client.persist_conflict = True
    assert (await broker.submit(conflict)).client_order_id == conflict.client_order_id
    missing = _command(BrokerOrderKind.TRAILING_STOP, trail=Decimal("5")).model_copy(
        update={"client_order_id": "vz-missing"}
    )
    client.timeout_submit = True
    with pytest.raises(AmbiguousBrokerResult):
        await broker.submit(missing)


@pytest.mark.anyio
async def test_alpaca_adapter_rejects_live_invalid_and_lookup_failures() -> None:
    client = _SdkClient()
    client._base_url = "https://api.alpaca.markets"
    with pytest.raises(ValueError, match="Paper"):
        _broker(client)
    client._base_url = "https://paper-api.alpaca.markets.evil.example"
    with pytest.raises(ValueError, match="Paper"):
        _broker(client)
    safe = _SdkClient()
    broker = _broker(safe)
    assert await broker.get_by_client_order_id("missing") is None
    safe.timeout_lookup = True
    with pytest.raises(AmbiguousBrokerResult):
        await broker.get_by_client_order_id("missing")
    with pytest.raises(ValueError, match="Invalid"):
        AlpacaPyBroker._request(_command(BrokerOrderKind.STOP))
    snapshot = AlpacaPyBroker._snapshot(
        _order(
            status=OrderStatus.FILLED,
            filled_qty="2",
            filled_avg_price="101.5",
            type=OrderType.STOP,
            stop_price="90",
        )
    )
    assert snapshot.average_fill_price == Decimal("101.5")
    assert snapshot.status == BrokerOrderStatus.FILLED
    assert snapshot.observed_at <= datetime.now(UTC)
