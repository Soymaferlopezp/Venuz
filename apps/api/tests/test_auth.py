from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.core import auth
from app.core.config import Settings


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class FakeAuthClient:
    def __init__(
        self, response: FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error

    async def __aenter__(self) -> FakeAuthClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, *_: object, **__: object) -> FakeResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def request_with(settings: Settings) -> Request:
    app = FastAPI()
    app.state.settings = settings
    return Request({"type": "http", "app": app})


@pytest.mark.anyio
async def test_auth_rejects_missing_or_empty_bearer(settings: Settings) -> None:
    request = request_with(settings)
    with pytest.raises(HTTPException) as missing:
        await auth.get_current_user(request, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as empty:
        await auth.get_current_user(request, "Bearer ")
    assert empty.value.status_code == 401


@pytest.mark.anyio
async def test_auth_validates_user_with_supabase(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    fake = FakeAuthClient(FakeResponse(200, {"id": "00000000-0000-0000-0000-000000000001"}))
    monkeypatch.setattr("app.core.auth.httpx.AsyncClient", lambda: fake)
    user = await auth.get_current_user(request_with(settings), "Bearer signed-user-token")
    assert str(user.id).endswith("0001")


@pytest.mark.anyio
async def test_auth_fails_closed_for_invalid_or_unavailable_supabase(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(
        "app.core.auth.httpx.AsyncClient", lambda: FakeAuthClient(FakeResponse(401, {}))
    )
    with pytest.raises(HTTPException) as invalid:
        await auth.get_current_user(request_with(settings), "Bearer invalid")
    assert invalid.value.status_code == 401

    error = httpx.ConnectError("offline", request=httpx.Request("GET", "https://example.test"))
    monkeypatch.setattr("app.core.auth.httpx.AsyncClient", lambda: FakeAuthClient(error=error))
    with pytest.raises(HTTPException) as unavailable:
        await auth.get_current_user(request_with(settings), "Bearer token")
    assert unavailable.value.status_code == 503
