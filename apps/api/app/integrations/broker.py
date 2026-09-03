from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class BrokerOrderKind(StrEnum):
    MARKET = "market"
    STOP = "stop"
    TRAILING_STOP = "trailing_stop"


class BrokerOrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class BrokerOrderCommand(BaseModel):
    model_config = ConfigDict(frozen=True)
    client_order_id: str = Field(min_length=1, max_length=48)
    symbol: str = Field(min_length=1, max_length=10)
    side: Literal["buy", "sell"]
    kind: BrokerOrderKind
    quantity: Decimal = Field(gt=0)
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None


class BrokerOrderSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    broker_order_id: str
    client_order_id: str = Field(min_length=1, max_length=48)
    symbol: str = Field(min_length=1, max_length=10)
    side: str
    kind: BrokerOrderKind
    status: BrokerOrderStatus
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None
    observed_at: datetime


class BrokerUnavailable(RuntimeError):
    pass


class AmbiguousBrokerResult(BrokerUnavailable):
    pass


class Broker(Protocol):
    async def submit(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot: ...
    async def get_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot | None: ...
    async def cancel(self, broker_order_id: str) -> None: ...
