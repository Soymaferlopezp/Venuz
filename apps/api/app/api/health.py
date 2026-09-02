from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["venuz-api"]
    trading_mode: Literal["paper"]
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return a lightweight, non-sensitive readiness response."""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service="venuz-api",
        trading_mode=settings.trading_mode,
        timestamp=datetime.now(UTC),
    )
