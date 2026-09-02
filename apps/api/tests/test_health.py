from fastapi.testclient import TestClient


def test_health_is_public_safe_and_typed(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "venuz-api"
    assert payload["trading_mode"] == "paper"
    assert payload["timestamp"].endswith("Z") or payload["timestamp"].endswith("+00:00")
    assert set(payload) == {"status", "service", "trading_mode", "timestamp"}
