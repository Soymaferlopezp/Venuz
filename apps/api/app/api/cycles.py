from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.domain.options import CycleMode, OptionsCapability
from app.services.cycles import CycleEvent, CycleRepository, CycleService, PublicCycle

router = APIRouter(prefix="/v1/cycles", tags=["public cycles"])


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_token: Annotated[str | None, Field(max_length=128)] = None
    mode: CycleMode = CycleMode.STOCKS


def _repository(request: Request) -> CycleRepository:
    return cast(CycleRepository, request.app.state.cycle_repository)


@router.post("/activate", response_model=PublicCycle)
async def activate_cycle(body: ActivationRequest, request: Request) -> PublicCycle:
    capability: OptionsCapability | None = None
    if body.mode in {CycleMode.OPTIONS, CycleMode.MIXED}:
        capability = await request.app.state.options_service.capability()
    return await CycleService(
        _repository(request), request.app.state.settings.strategy_version
    ).activate(mode=body.mode, capability=capability)


@router.get("/latest", response_model=PublicCycle)
async def latest_cycle(request: Request) -> PublicCycle:
    cycle = await _repository(request).latest()
    if cycle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No real cycle is available"
        )
    return cycle


@router.get("/{cycle_id}", response_model=PublicCycle)
async def get_cycle(cycle_id: str, request: Request) -> PublicCycle:
    cycle = await _repository(request).get(cycle_id)
    if cycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found")
    return cycle


@router.get("/{cycle_id}/events")
async def cycle_events(cycle_id: str, request: Request) -> tuple[CycleEvent, ...]:
    return (await get_cycle(cycle_id, request)).events
