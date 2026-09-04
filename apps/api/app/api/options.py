from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.domain.options import OptionFeed, OptionGuard, OptionsCapability
from app.repositories.options import OptionRepository
from app.services.options import OptionsService

router = APIRouter(tags=["public options observation"])


class PublicOptionsCapability(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    options_approved_level: int | None
    options_trading_level: int | None
    options_buying_power_available: bool
    paper_endpoint_valid: bool
    option_assets_available: bool
    contracts_accessible: bool
    chains_accessible: bool
    snapshots_accessible: bool
    feed: OptionFeed | None
    checked_at: datetime
    blocking_reasons: tuple[str, ...]
    requirement: str = "Cash-Secured Puts require Alpaca Options Level 1"


class PublicOptionEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)
    underlying: str
    occ_symbol: str
    strike: Decimal
    expiration: date
    dte: int
    delta: Decimal | None
    current_implied_volatility: Decimal | None
    realized_volatility: Decimal | None
    realized_volatility_window: int
    iv_relative_ratio: Decimal | None
    iv_signal_quality: str
    bid: Decimal | None
    ask: Decimal | None
    spread_absolute: Decimal | None
    spread_pct: Decimal | None
    collateral: Decimal
    feed: OptionFeed | None
    provider: str
    data_freshness: str
    eligible: bool
    score: Decimal | None
    guards: tuple[OptionGuard, ...]
    rejected_reasons: tuple[str, ...]


class PublicOptionOrder(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_id: str
    occ_symbol: str
    underlying: str
    position_intent: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    observed_at: datetime


class PublicOptionPosition(BaseModel):
    model_config = ConfigDict(frozen=True)
    position_id: str
    occ_symbol: str
    underlying: str
    strike: Decimal
    expiration: date
    contracts: int
    entry_credit_per_share: Decimal
    entry_credit_total: Decimal
    collateral: Decimal
    status: str
    exit_reason: str
    updated_at: datetime


class PublicOptionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: str
    state: str
    reason: str
    sanitized_details: dict[str, str]
    occurred_at: datetime


class PublicOptionCycle(BaseModel):
    model_config = ConfigDict(frozen=True)
    cycle_id: str
    capability_status: str
    selected_contract: str | None
    evaluations: tuple[PublicOptionEvaluation, ...]
    orders: tuple[PublicOptionOrder, ...]
    positions: tuple[PublicOptionPosition, ...]
    events: tuple[PublicOptionEvent, ...]
    settlements: tuple[PublicOptionEvent, ...]


def _service(request: Request) -> OptionsService:
    return cast(OptionsService, request.app.state.options_service)


def _repository(request: Request) -> OptionRepository:
    return cast(OptionRepository, request.app.state.options_repository)


@router.get("/v1/options/capability", response_model=PublicOptionsCapability)
async def options_capability(request: Request) -> PublicOptionsCapability:
    capability: OptionsCapability = await _service(request).capability()
    return PublicOptionsCapability.model_validate(capability.model_dump())


@router.get("/v1/cycles/{cycle_id}/options", response_model=PublicOptionCycle)
async def option_cycle(cycle_id: str, request: Request) -> PublicOptionCycle:
    snapshot = await _repository(request).cycle_snapshot(cycle_id)
    evaluations = tuple(
        PublicOptionEvaluation(
            underlying=item.candidate.underlying,
            occ_symbol=item.candidate.occ_symbol,
            strike=item.candidate.strike,
            expiration=item.candidate.expiration,
            dte=(item.candidate.expiration - item.candidate.observed_at.date()).days,
            delta=item.candidate.delta,
            current_implied_volatility=item.candidate.implied_volatility,
            realized_volatility=item.candidate.realized_volatility,
            realized_volatility_window=item.candidate.realized_volatility_window,
            iv_relative_ratio=item.iv_relative_ratio,
            iv_signal_quality=item.iv_signal_quality.value,
            bid=item.candidate.bid,
            ask=item.candidate.ask,
            spread_absolute=item.spread_absolute,
            spread_pct=item.spread_pct,
            collateral=item.collateral,
            feed=item.candidate.feed,
            provider=item.candidate.provider,
            data_freshness="fresh" if item.eligible else "insufficient",
            eligible=item.eligible,
            score=item.score,
            guards=item.guards,
            rejected_reasons=item.rejected_reasons,
        )
        for item in snapshot.evaluations
    )
    orders = tuple(
        PublicOptionOrder(
            order_id=item.order_id,
            occ_symbol=item.occ_symbol,
            underlying=item.underlying,
            position_intent=item.position_intent,
            status=item.status.value,
            quantity=item.quantity,
            filled_quantity=item.filled_quantity,
            average_fill_price=item.average_fill_price,
            observed_at=item.observed_at,
        )
        for item in snapshot.orders
    )
    positions = tuple(
        PublicOptionPosition(
            position_id=item.position_id,
            occ_symbol=item.occ_symbol,
            underlying=item.underlying,
            strike=item.strike,
            expiration=item.expiration,
            contracts=item.contracts,
            entry_credit_per_share=item.entry_credit_per_share,
            entry_credit_total=item.entry_credit_total,
            collateral=item.collateral,
            status=item.status.value,
            exit_reason=item.exit_reason.value,
            updated_at=item.updated_at,
        )
        for item in snapshot.positions
    )
    events = tuple(
        PublicOptionEvent(
            event_type=item.event_type,
            state=item.state,
            reason=item.reason,
            sanitized_details=item.sanitized_details,
            occurred_at=item.occurred_at,
        )
        for item in snapshot.events
    )
    settlements = tuple(
        PublicOptionEvent(
            event_type=f"option.activity.{item.activity_type.lower()}",
            state="processed",
            reason="alpaca_account_activity",
            sanitized_details={
                "underlying": item.underlying,
                "shares": str(item.shares),
            },
            occurred_at=item.occurred_at,
        )
        for item in snapshot.settlements
    )
    return PublicOptionCycle(
        cycle_id=cycle_id,
        capability_status=snapshot.capability_status,
        selected_contract=snapshot.selected_contract,
        evaluations=evaluations,
        orders=orders,
        positions=positions,
        events=events,
        settlements=settlements,
    )
