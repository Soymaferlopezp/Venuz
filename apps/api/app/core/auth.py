from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID


async def _fetch_user(client: Any, request: Request, token: str) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        response = await client.get(
            f"{str(settings.supabase_url).rstrip(chr(47))}/auth/v1/user",
            headers={
                "apikey": settings.supabase_secret_key.get_secret_value(),
                "Authorization": f"Bearer {token}",
            },
            timeout=8,
        )
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication unavailable",
        ) from error
    status_code = getattr(response, "status_code", 500)
    if status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )
    payload = response.json()
    if not isinstance(payload, dict) or "id" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )
    return payload


async def get_current_user(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> AuthenticatedUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if hasattr(request.app.state, "http_client"):
        payload = await _fetch_user(request.app.state.http_client, request, token)
    else:
        async with httpx.AsyncClient() as client:
            payload = await _fetch_user(client, request, token)
    return AuthenticatedUser(id=UUID(str(payload["id"])))
