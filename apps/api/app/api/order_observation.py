from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.domain.order_lifecycle import PositionMode
from app.integrations.broker import BrokerOrderKind, BrokerOrderStatus
from app.repositories.orders import OrderRepository

router = APIRouter(prefix="/v1/cycles", tags=["public order observation"])


class PublicOrder(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_id: str
    symbol: str
    purpose: str
    side: str
    order_type: BrokerOrderKind
    status: BrokerOrderStatus
    quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    stop_price: Decimal | None
    trail_percent: Decimal | None
    observed_at: datetime


class PublicApproval(BaseModel):
    model_config = ConfigDict(frozen=True)
    approval_id: str
    symbol: str
    reason_code: str
    status: str
    evidence_links: tuple[str, ...]
    created_at: datetime


class PublicAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    audit_id: str
    event_type: str
    symbol: str
    decision: str
    correlation_id: str
    sanitized_details: dict[str, str]
    occurred_at: datetime


class PublicPosition(BaseModel):
    model_config = ConfigDict(frozen=True)
    position_id: str
    symbol: str
    quantity: Decimal
    average_fill_price: Decimal
    estimated_price: Decimal | None
    protection_mode: PositionMode
    updated_at: datetime


def _repository(request: Request) -> OrderRepository:
    return cast(OrderRepository, request.app.state.order_repository)


@router.get("/{cycle_id}/orders", response_model=tuple[PublicOrder, ...])
async def cycle_orders(cycle_id: str, request: Request) -> tuple[PublicOrder, ...]:
    return tuple(
        PublicOrder(
            order_id=item.order_id,
            symbol=item.symbol,
            purpose=item.purpose.value,
            side=item.side,
            order_type=item.kind,
            status=item.status,
            quantity=item.quantity,
            filled_quantity=item.filled_quantity,
            average_fill_price=item.average_fill_price,
            stop_price=item.stop_price,
            trail_percent=item.trail_percent,
            observed_at=item.observed_at,
        )
        for item in await _repository(request).cycle_orders(cycle_id)
    )


@router.get("/{cycle_id}/approvals", response_model=tuple[PublicApproval, ...])
async def cycle_approvals(cycle_id: str, request: Request) -> tuple[PublicApproval, ...]:
    return tuple(
        PublicApproval(
            approval_id=item.approval_id,
            symbol=item.symbol,
            reason_code=item.reason_code,
            status=item.status,
            evidence_links=item.evidence_links,
            created_at=item.created_at,
        )
        for item in await _repository(request).cycle_approvals(cycle_id)
    )


@router.get("/{cycle_id}/audit", response_model=tuple[PublicAuditEvent, ...])
async def cycle_audit(cycle_id: str, request: Request) -> tuple[PublicAuditEvent, ...]:
    return tuple(
        PublicAuditEvent.model_validate(item.model_dump())
        for item in await _repository(request).cycle_audit(cycle_id)
    )
