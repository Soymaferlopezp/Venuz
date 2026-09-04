from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.domain.options import CycleMode, OptionsCapability
from app.services.cycles import CycleService, MemoryCycleRepository
from app.services.options import OptionsService
from tests.fakes.options import FakeOptionsGateway
from tests.test_phase3b_options_lifecycle import NOW


@pytest.mark.anyio
async def test_concurrent_activation_is_one_cycle_per_mode_and_key() -> None:
    repository = MemoryCycleRepository()
    service = CycleService(repository, "2026.09")
    options = await asyncio.gather(
        *(service.activate(NOW, mode=CycleMode.OPTIONS) for _ in range(10))
    )
    stocks = await service.activate(NOW, mode=CycleMode.STOCKS)
    assert len({item.cycle_id for item in options}) == 1
    assert options[0].cycle_id != stocks.cycle_id
    assert ":options:" in options[0].cycle_key and ":stocks:" in stocks.cycle_key


def test_level_zero_blocks_options_but_not_stocks(client: TestClient) -> None:
    app: Any = client.app
    service = cast(OptionsService, app.state.options_service)
    gateway = cast(FakeOptionsGateway, service.gateway)
    gateway.capability_result = OptionsCapability(
        status="blocked",
        options_approved_level=0,
        options_trading_level=0,
        paper_endpoint_valid=True,
        checked_at=NOW,
        blocking_reasons=("options_approved_level_1_required", "options_trading_level_1_required"),
    )
    options = client.post("/v1/cycles/activate", json={"mode": "options"})
    stocks = client.post("/v1/cycles/activate", json={"mode": "stocks"})
    assert options.status_code == 200 and options.json()["options_capability_status"] == "blocked"
    assert options.json()["state"] == "blocked"
    assert "options_approved_level_1_required" in options.json()["blocked_reasons"]
    assert (
        stocks.status_code == 200 and stocks.json()["options_capability_status"] == "not_required"
    )


def test_unavailable_capability_blocks_options_and_mixed_but_not_stocks(
    client: TestClient,
) -> None:
    app: Any = client.app
    service = cast(OptionsService, app.state.options_service)
    gateway = cast(FakeOptionsGateway, service.gateway)
    gateway.capability_result = OptionsCapability(
        status="unavailable",
        paper_endpoint_valid=True,
        checked_at=NOW,
        blocking_reasons=("alpaca_account_timeout",),
    )
    options = client.post("/v1/cycles/activate", json={"mode": "options"}).json()
    mixed = client.post("/v1/cycles/activate", json={"mode": "mixed"}).json()
    stocks = client.post("/v1/cycles/activate", json={"mode": "stocks"}).json()
    assert options["state"] == "blocked" and mixed["state"] == "blocked"
    assert options["options_capability_status"] == "unavailable"
    assert mixed["options_capability_status"] == "unavailable"
    assert stocks["state"] == "queued"
    assert stocks["options_capability_status"] == "not_required"
