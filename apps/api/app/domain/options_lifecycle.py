from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.options import OptionEvaluation, OptionExitReason
from app.integrations.broker import BrokerOrderStatus


class OptionPositionStatus(StrEnum):
    OPEN = "open"
    CLOSING = "closing"
    ASSIGNED = "assigned"
    EXPIRED = "expired"
    CLOSED = "closed"


class CollateralStatus(StrEnum):
    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"


class OptionOrderRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_id: str
    cycle_id: str
    option_position_id: str | None = None
    intent_key: str
    client_order_id: str
    occ_symbol: str
    underlying: str
    position_intent: Literal["sell_to_open", "buy_to_close"]
    status: BrokerOrderStatus
    quantity: Decimal = Field(gt=0, le=1)
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    average_fill_price: Decimal | None = None
    broker_order_id: str | None = None
    observed_at: datetime


class OptionPositionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    position_id: str
    cycle_id: str
    occ_symbol: str
    underlying: str
    sector: str
    contracts: int = Field(ge=0, le=1)
    strike: Decimal = Field(gt=0)
    expiration: date
    entry_credit_per_share: Decimal = Field(gt=0)
    entry_credit_total: Decimal = Field(gt=0)
    collateral: Decimal = Field(gt=0)
    status: OptionPositionStatus
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    exit_reason: OptionExitReason = OptionExitReason.NONE


class CollateralReservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reservation_id: str
    cycle_id: str
    intent_key: str
    occ_symbol: str
    underlying: str
    sector: str
    amount: Decimal = Field(gt=0)
    status: CollateralStatus
    reserved_at: datetime
    released_at: datetime | None = None


class OptionLifecycleEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    cycle_id: str
    option_position_id: str | None = None
    event_type: str
    state: str
    reason: str
    sanitized_details: dict[str, str]
    occurred_at: datetime


class OptionSettlementEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    activity_id: str
    cycle_id: str
    option_position_id: str
    activity_type: str
    occ_symbol: str
    underlying: str
    shares: int = Field(ge=0, le=100)
    cash_effect: Decimal | None = None
    occurred_at: datetime


class OptionCycleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cycle_id: str
    capability_status: str
    selected_contract: str | None
    evaluations: tuple[OptionEvaluation, ...]
    orders: tuple[OptionOrderRecord, ...]
    positions: tuple[OptionPositionRecord, ...]
    events: tuple[OptionLifecycleEvent, ...]
    settlements: tuple[OptionSettlementEvent, ...]
