from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

JsonObject = dict[str, Any]
JsonValue = JsonObject | list[Any]


class ProviderError(RuntimeError):
    """A sanitized provider failure that is safe to expose as NO_TRADE evidence."""


class CacheStore(Protocol):
    async def get(self, key: str, now: datetime) -> JsonValue | None: ...

    async def put(self, key: str, value: JsonValue, expires_at: datetime) -> None: ...


class MemoryCacheStore:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[datetime, JsonValue]] = {}

    async def get(self, key: str, now: datetime) -> JsonValue | None:
        entry = self._entries.get(key)
        return entry[1] if entry is not None and entry[0] >= now else None

    async def put(self, key: str, value: JsonValue, expires_at: datetime) -> None:
        self._entries[key] = (expires_at, value)


def cache_key(provider: str, operation: str, params: Mapping[str, str]) -> str:
    canonical = json.dumps(dict(sorted(params.items())), separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{provider}:{operation}:{digest}"


class AsyncJsonClient:
    def __init__(
        self,
        *,
        provider: str,
        client: httpx.AsyncClient,
        cache: CacheStore,
        timeout_seconds: float = 10,
        max_attempts: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.provider = provider
        self.client = client
        self.cache = cache
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.jitter = jitter

    async def get_json(
        self,
        url: str,
        *,
        operation: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        ttl: timedelta,
        now: datetime,
        retry_quota: bool = True,
        cache_params: Mapping[str, str] | None = None,
    ) -> tuple[JsonValue, str, bool]:
        key = cache_key(self.provider, operation, cache_params or params)
        cached = await self.cache.get(key, now)
        if cached is not None:
            return cached, key, True
        for attempt in range(self.max_attempts):
            try:
                response = await self.client.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
                if response.status_code == 429 and not retry_quota:
                    raise ProviderError(f"{self.provider} quota exhausted")
                if (
                    response.status_code == 429 or response.status_code >= 500
                ) and attempt + 1 < self.max_attempts:
                    await self.sleep(DecimalBackoff.seconds(attempt, self.jitter()))
                    continue
                response.raise_for_status()
                payload: object = response.json()
                if not isinstance(payload, dict | list):
                    raise ProviderError(f"{self.provider} returned invalid JSON")
                await self.cache.put(key, payload, now + ttl)
                return payload, key, False
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if attempt + 1 >= self.max_attempts:
                    raise ProviderError(f"{self.provider} unavailable") from error
                await self.sleep(DecimalBackoff.seconds(attempt, self.jitter()))
            except httpx.HTTPStatusError as error:
                raise ProviderError(f"{self.provider} rejected the sanitized request") from error
        raise ProviderError(f"{self.provider} unavailable")


class DecimalBackoff:
    @staticmethod
    def seconds(attempt: int, jitter: float = 0) -> float:
        base = min(0.25 * (2**attempt), 2.0)
        return float(min(base + max(0, min(jitter, 1)) * 0.1, 2.1))


def utc_now() -> datetime:
    return datetime.now(UTC)
