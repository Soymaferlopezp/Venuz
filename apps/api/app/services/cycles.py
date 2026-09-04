from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict

from app.domain.options import AssetClass, CycleMode, OptionsCapability
from app.domain.paper_execution import CycleState, assert_transition, cycle_key


class CycleEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: CycleState
    occurred_at: datetime
    message: str


class PublicCycle(BaseModel):
    model_config = ConfigDict(frozen=True)
    cycle_id: str
    cycle_key: str
    mode: CycleMode = CycleMode.STOCKS
    selected_asset_class: AssetClass | None = None
    options_capability_status: str = "not_required"
    state: CycleState
    historical: bool = False
    data_freshness: str = "fresh"
    paper_order_submitted: bool = False
    blocked_reasons: tuple[str, ...] = ()
    evidence_links: tuple[str, ...] = ()
    provider_provenance: tuple[str, ...] = ()
    events: tuple[CycleEvent, ...] = ()
    updated_at: datetime


class CycleRepository(Protocol):
    async def activate(
        self,
        key: str,
        now: datetime,
        mode: CycleMode = CycleMode.STOCKS,
        capability: OptionsCapability | None = None,
    ) -> PublicCycle: ...
    async def get(self, cycle_id: str) -> PublicCycle | None: ...
    async def latest(self) -> PublicCycle | None: ...


class MemoryCycleRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_key: dict[str, PublicCycle] = {}
        self._by_id: dict[str, PublicCycle] = {}

    async def activate(
        self,
        key: str,
        now: datetime,
        mode: CycleMode = CycleMode.STOCKS,
        capability: OptionsCapability | None = None,
    ) -> PublicCycle:
        async with self._lock:
            if key in self._by_key:
                return self._by_key[key]
            cycle_id = str(uuid5(NAMESPACE_URL, f"venuz-cycle:{key}"))
            initial_state = (
                CycleState.BLOCKED
                if capability is not None and not capability.eligible
                else CycleState.QUEUED
            )
            event = CycleEvent(
                state=initial_state,
                occurred_at=now,
                message="Options capability blocked"
                if initial_state == CycleState.BLOCKED
                else "Cycle queued",
            )
            cycle = PublicCycle(
                cycle_id=cycle_id,
                cycle_key=key,
                mode=mode,
                options_capability_status=capability.status if capability else "not_required",
                state=initial_state,
                blocked_reasons=capability.blocking_reasons if capability else (),
                events=(event,),
                updated_at=now,
            )
            self._by_key[key] = cycle
            self._by_id[cycle_id] = cycle
            return cycle

    async def get(self, cycle_id: str) -> PublicCycle | None:
        return self._by_id.get(cycle_id)

    async def latest(self) -> PublicCycle | None:
        if not self._by_id:
            return None
        cycle = max(self._by_id.values(), key=lambda item: item.updated_at)
        return cycle.model_copy(update={"historical": True})

    async def transition(
        self,
        cycle_id: str,
        target: CycleState,
        now: datetime,
        message: str,
        *,
        blocked_reasons: tuple[str, ...] = (),
        paper_order_submitted: bool = False,
    ) -> PublicCycle:
        async with self._lock:
            current = self._by_id[cycle_id]
            assert_transition(current.state, target)
            event = CycleEvent(state=target, occurred_at=now, message=message)
            updated = current.model_copy(
                update={
                    "state": target,
                    "blocked_reasons": blocked_reasons,
                    "paper_order_submitted": current.paper_order_submitted or paper_order_submitted,
                    "events": (*current.events, event),
                    "updated_at": now,
                }
            )
            self._by_id[cycle_id] = updated
            self._by_key[current.cycle_key] = updated
            return updated


class CycleService:
    def __init__(self, repository: CycleRepository, strategy_version: str) -> None:
        self.repository = repository
        self.strategy_version = strategy_version

    async def activate(
        self,
        now: datetime | None = None,
        *,
        market_session: date | None = None,
        data_cutoff: datetime | None = None,
        mode: CycleMode = CycleMode.STOCKS,
        capability: OptionsCapability | None = None,
    ) -> PublicCycle:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        session = market_session or instant.date()
        cutoff = data_cutoff or instant.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.repository.activate(
            cycle_key(self.strategy_version, session, cutoff, mode),
            instant,
            mode,
            capability,
        )
