from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.domain.paper_execution import protection_prices
from app.integrations.broker import BrokerOrderKind, BrokerOrderStatus


class OrderPurpose(StrEnum):
    ENTRY = "entry"
    INITIAL_STOP = "initial_stop"
    ESTIMATED_PRICE_STOP = "estimated_price_stop"
    TRAILING_STOP = "trailing_stop"
    CRITICAL_EXIT = "critical_exit"


class PositionMode(StrEnum):
    INITIAL = "initial"
    ESTIMATED_PRICE = "estimated_price"
    TRAILING = "trailing"
    EXITING = "exiting"
    CLOSED = "closed"


class FundamentalSeverity(StrEnum):
    CRITICAL = "critical"
    NONCRITICAL_RED = "noncritical_red"


class OrderRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_id: str
    cycle_id: str
    position_id: str | None = None
    intent_key: str
    client_order_id: str
    symbol: str
    purpose: OrderPurpose
    side: str
    kind: BrokerOrderKind
    status: BrokerOrderStatus
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price: Decimal | None = None
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None
    broker_order_id: str | None = None
    observed_at: datetime


class PositionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    position_id: str
    cycle_id: str
    symbol: str
    quantity: Decimal = Field(ge=0)
    entry_filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    exit_filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price: Decimal = Field(gt=0)
    estimated_price: Decimal | None = None
    mode: PositionMode = PositionMode.INITIAL
    updated_at: datetime


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    approval_id: str
    cycle_id: str
    symbol: str
    reason_code: str
    status: str = "pending"
    evidence_links: tuple[str, ...] = ()
    created_at: datetime


class AuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    audit_id: str
    cycle_id: str
    event_type: str
    symbol: str
    decision: str
    correlation_id: str
    sanitized_details: dict[str, str]
    occurred_at: datetime


class ProtectionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    purpose: OrderPurpose
    kind: BrokerOrderKind
    stop_price: Decimal | None = None
    trail_percent: Decimal | None = None
    mode: PositionMode
    reason: str


def stable_identifier(namespace: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"venuz:{namespace}:{value}"))


def broker_client_order_id(intent_key: str) -> str:
    return f"vz-{uuid5(NAMESPACE_URL, intent_key).hex}"


def initial_protection(fill_price: Decimal) -> ProtectionPlan:
    stop, _ = protection_prices(fill_price)
    return ProtectionPlan(
        purpose=OrderPurpose.INITIAL_STOP,
        kind=BrokerOrderKind.STOP,
        stop_price=stop,
        mode=PositionMode.INITIAL,
        reason="initial_stop_10_percent_below_average_fill",
    )


def protection_for_price(position: PositionRecord, market_price: Decimal) -> ProtectionPlan | None:
    _, objective = protection_prices(position.average_fill_price)
    estimated = position.estimated_price
    estimated_branch_first = estimated is not None and estimated < objective
    if (
        estimated_branch_first
        and estimated is not None
        and market_price >= estimated * Decimal("1.05")
    ):
        return ProtectionPlan(
            purpose=OrderPurpose.TRAILING_STOP,
            kind=BrokerOrderKind.TRAILING_STOP,
            trail_percent=Decimal("5"),
            mode=PositionMode.TRAILING,
            reason="estimated_price_plus_5_percent_reached_trail_5_percent",
        )
    if position.mode == PositionMode.ESTIMATED_PRICE:
        return None
    if market_price >= objective:
        return ProtectionPlan(
            purpose=OrderPurpose.TRAILING_STOP,
            kind=BrokerOrderKind.TRAILING_STOP,
            trail_percent=Decimal("5"),
            mode=PositionMode.TRAILING,
            reason="plus_2r_reached_keep_100_percent_and_trail_5_percent",
        )
    if estimated is not None and market_price >= estimated:
        return ProtectionPlan(
            purpose=OrderPurpose.ESTIMATED_PRICE_STOP,
            kind=BrokerOrderKind.STOP,
            stop_price=(estimated * Decimal("0.95")).quantize(Decimal("0.01")),
            mode=PositionMode.ESTIMATED_PRICE,
            reason="estimated_price_reached_protect_5_percent_below",
        )
    return None
