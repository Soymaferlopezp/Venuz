from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

from app.integrations.alpaca_options import OptionAccountActivity
from app.repositories.options import MemoryOptionRepository
from app.services.options import OptionsService
from tests.fakes.broker import FakeBroker
from tests.test_phase3b_options_lifecycle import NOW, valid_evaluation


def test_public_options_endpoints_are_complete_and_sanitized(client: TestClient) -> None:
    capability = client.get("/v1/options/capability")
    assert capability.status_code == 200
    assert capability.json()["requirement"] == "Cash-Secured Puts require Alpaca Options Level 1"

    app: Any = client.app
    service = cast(OptionsService, app.state.options_service)
    repository = cast(MemoryOptionRepository, app.state.options_repository)
    broker = cast(FakeBroker, service.broker)
    evaluation, portfolio = valid_evaluation()
    order = asyncio.run(service.submit_entry("public-cycle", evaluation, portfolio, NOW))
    broker.fill(order.client_order_id, Decimal("1"), Decimal("1"))
    asyncio.run(service.reconcile_entry(order.intent_key, evaluation))
    asyncio.run(
        service.process_activity(
            "public-cycle",
            OptionAccountActivity(
                activity_id="public-assignment",
                activity_type="OPASN",
                symbol=evaluation.candidate.occ_symbol,
                quantity=Decimal("1"),
                price=Decimal("30"),
                occurred_at=NOW + timedelta(days=1),
            ),
        )
    )

    response = client.get("/v1/cycles/public-cycle/options")
    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluations"] and payload["orders"] and payload["positions"]
    assert payload["events"] and payload["settlements"]
    serialized = response.text.lower()
    assert "intent_key" not in serialized
    assert "client_order_id" not in serialized
    assert "broker_order_id" not in serialized
    assert "authorization" not in serialized
    assert repository.settlements
