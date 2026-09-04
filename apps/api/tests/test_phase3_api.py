from typing import Any, cast

from fastapi.testclient import TestClient


def test_public_cycle_routes_are_sanitized_and_idempotent(client: TestClient) -> None:
    first = client.post("/v1/cycles/activate", json={}).json()
    second = client.post("/v1/cycles/activate", json={"request_token": "retry"}).json()
    assert first["cycle_id"] == second["cycle_id"]
    assert set(first) == {
        "cycle_id",
        "cycle_key",
        "mode",
        "selected_asset_class",
        "options_capability_status",
        "state",
        "historical",
        "data_freshness",
        "paper_order_submitted",
        "blocked_reasons",
        "evidence_links",
        "provider_provenance",
        "events",
        "updated_at",
    }
    assert "secret" not in str(first).lower() and "authorization" not in str(first).lower()
    assert client.get(f"/v1/cycles/{first['cycle_id']}").status_code == 200
    assert client.get(f"/v1/cycles/{first['cycle_id']}/events").status_code == 200
    assert client.get("/v1/cycles/latest").json()["historical"] is True


def test_public_cycle_routes_validate_and_404(client: TestClient) -> None:
    assert client.post("/v1/cycles/activate", json={"unexpected": True}).status_code == 422
    assert client.get("/v1/cycles/missing").status_code == 404
    assert client.get("/v1/cycles/missing/events").status_code == 404
    fresh_client = client
    repository = cast(Any, fresh_client.app).state.cycle_repository
    repository._by_id.clear()
    repository._by_key.clear()
    assert fresh_client.get("/v1/cycles/latest").status_code == 404
