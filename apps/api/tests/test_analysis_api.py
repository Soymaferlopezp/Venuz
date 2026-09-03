from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedUser, get_current_user
from app.integrations.alpha_vantage import BudgetExhausted
from app.integrations.base import ProviderError
from app.repositories.analysis import AnalysisRepository
from app.services.analysis import build_fixture_thesis

TEST_USER = AuthenticatedUser(id=UUID("00000000-0000-0000-0000-000000000001"))


async def authenticated_user() -> AuthenticatedUser:
    return TEST_USER


def app_from(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


class FakeProviderService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def analyze(self, owner_id: str, symbol: str, now: datetime) -> object:
        if self.error is not None:
            raise self.error
        thesis = build_fixture_thesis(symbol, now)
        repository = cast(AnalysisRepository, self.repository)
        await repository.save_thesis(owner_id, thesis)
        return thesis

    repository: object


def authenticate(client: TestClient) -> FastAPI:
    app = app_from(client)
    app.dependency_overrides[get_current_user] = authenticated_user
    return app


def test_analysis_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/analysis/AAPL", json={"mode": "fixture"}).status_code == 401
    assert client.get("/v1/providers/status").status_code == 401


def test_fixture_analysis_criteria_valuation_evidence_and_latest(client: TestClient) -> None:
    app = authenticate(client)
    try:
        created = client.post("/v1/analysis/AAPL", json={"mode": "fixture"})
        assert created.status_code == 200
        assert created.json()["company"]["ticker"] == "AAPL"
        assert len(created.json()["criteria"]) == 7
        assert all(item["evidence_ids"] for item in created.json()["criteria"])
        assert client.get("/v1/analysis/AAPL/latest").status_code == 200
        assert len(client.get("/v1/analysis/AAPL/criteria").json()) == 7
        assert len(client.get("/v1/analysis/AAPL/evidence").json()) == 3
        valuation = client.get("/v1/analysis/AAPL/valuation").json()
        assert valuation["estimated_price_pe"] != valuation["estimated_price_pfcf"]
        assert client.get("/v1/analysis/MSFT/latest").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_provider_analysis_success_and_fail_closed_states(client: TestClient) -> None:
    app = authenticate(client)
    repository = app.state.analysis_repository
    success = FakeProviderService()
    success.repository = repository
    app.state.analysis_service = success
    try:
        response = client.post("/v1/analysis/AAPL", json={"mode": "provider"})
        assert response.status_code == 200
        app.state.analysis_service = FakeProviderService(BudgetExhausted("daily budget exhausted"))
        exhausted = client.post("/v1/analysis/MSFT", json={"mode": "provider"})
        assert exhausted.status_code == 429
        assert exhausted.json()["detail"]["state"] == "provider_exhausted"
        app.state.analysis_service = FakeProviderService(ProviderError("SEC unavailable"))
        unavailable = client.post("/v1/analysis/NVDA", json={"mode": "provider"})
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["state"] == "error"
        assert client.post("/v1/orders", json={}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_watchlist_provider_status_and_fixture_compatibility(client: TestClient) -> None:
    app = authenticate(client)
    try:
        built = client.post("/v1/watchlists/build?mode=fixture")
        assert built.status_code == 200
        assert len(built.json()["items"]) == 10
        symbols = [item["company"]["ticker"] for item in built.json()["items"]]
        assert symbols == sorted(symbols)
        assert len(client.get("/v1/watchlists/latest").json()["items"]) == 10
        status = client.get("/v1/providers/status")
        assert status.status_code == 200
        serialized = status.text.lower()
        assert "secret" not in serialized and "authorization" not in serialized
        assert status.json()["alpha_vantage_budget"]["request_count"] == 0
        compatibility = client.post("/v1/analysis/AAPL", json={"fixture_mode": True})
        assert compatibility.status_code == 200
    finally:
        app.dependency_overrides.clear()
