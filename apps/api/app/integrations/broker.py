from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    kind: BrokerOrderKind
    quantity: Decimal = Field(gt=0)
    asset_class: Literal["stock", "option"] = "stock"
    position_intent: Literal["sell_to_open", "buy_to_close"] | None = None
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None

    @model_validator(mode="after")
    def option_contract_is_safe(self) -> Self:
        if self.asset_class == "option":
            if self.kind != BrokerOrderKind.MARKET or self.quantity != Decimal("1"):
                raise ValueError("Options orders require one whole market contract")
            if self.position_intent not in {"sell_to_open", "buy_to_close"}:
                raise ValueError("Options orders require an approved position intent")
            expected_side = "sell" if self.position_intent == "sell_to_open" else "buy"
            if self.side != expected_side:
                raise ValueError("Options side and position intent are inconsistent")
        elif self.position_intent is not None:
            raise ValueError("Stock orders cannot use an options position intent")
        return self


class BrokerOrderSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    broker_order_id: str
    client_order_id: str = Field(min_length=1, max_length=48)
    symbol: str = Field(min_length=1, max_length=32)
    side: str
    kind: BrokerOrderKind
    status: BrokerOrderStatus
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None
    asset_class: Literal["stock", "option"] = "stock"
    position_intent: Literal["sell_to_open", "buy_to_close"] | None = None
    observed_at: datetime


class BrokerUnavailable(RuntimeError):
    pass


class AmbiguousBrokerResult(BrokerUnavailable):
    pass


class Broker(Protocol):
    async def submit(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot: ...
    async def get_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot | None: ...
    async def cancel(self, broker_order_id: str) -> None: ...
