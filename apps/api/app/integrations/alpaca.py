from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.base import AsyncJsonClient, JsonObject, ProviderError


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ProviderError(f"Alpaca {field} is invalid") from error
    if not result.is_finite():
        raise ProviderError(f"Alpaca {field} is invalid")
    return result


def parse_asset(payload: Mapping[str, Any]) -> JsonObject:
    required = ("symbol", "class", "exchange", "tradable", "status")
    if any(field not in payload for field in required):
        raise ProviderError("Alpaca asset response is incomplete")
    return {field: payload[field] for field in required} | {
        "name": payload.get("name", payload["symbol"])
    }


def parse_snapshot(payload: Mapping[str, Any]) -> JsonObject:
    trade = payload.get("latestTrade")
    quote = payload.get("latestQuote")
    if not isinstance(trade, dict) or not isinstance(quote, dict):
        raise ProviderError("Alpaca snapshot is incomplete")
    price = _decimal(trade.get("p"), "trade price")
    bid = _decimal(quote.get("bp"), "bid")
    ask = _decimal(quote.get("ap"), "ask")
    if price <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        raise ProviderError("Alpaca snapshot is contradictory")
    return {"price": str(price), "bid": str(bid), "ask": str(ask), "timestamp": trade.get("t")}


def parse_calendar(payload: object) -> tuple[date, ...]:
    if not isinstance(payload, list):
        raise ProviderError("Alpaca calendar response is invalid")
    try:
        return tuple(
            date.fromisoformat(str(item["date"])) for item in payload if isinstance(item, dict)
        )
    except (KeyError, ValueError) as error:
        raise ProviderError("Alpaca calendar contains an invalid session") from error


def parse_news(payload: Mapping[str, Any]) -> tuple[JsonObject, ...]:
    news = payload.get("news")
    if not isinstance(news, list):
        raise ProviderError("Alpaca news response is invalid")
    return tuple(
        {
            "id": str(item["id"]),
            "headline": str(item["headline"]),
            "url": str(item["url"]),
            "created_at": str(item["created_at"]),
        }
        for item in news
        if isinstance(item, dict) and {"id", "headline", "url", "created_at"} <= item.keys()
    )


def parse_bars(payload: Mapping[str, Any], symbol: str) -> tuple[JsonObject, ...]:
    container = payload.get("bars")
    raw_bars = container.get(symbol, []) if isinstance(container, dict) else container
    if not isinstance(raw_bars, list):
        raise ProviderError("Alpaca bars response is invalid")
    parsed: list[JsonObject] = []
    for item in raw_bars:
        if not isinstance(item, dict):
            continue
        close = _decimal(item.get("c"), "bar close")
        volume = _decimal(item.get("v"), "bar volume")
        timestamp = item.get("t")
        if close <= 0 or volume < 0 or not isinstance(timestamp, str):
            raise ProviderError("Alpaca bar is contradictory")
        parsed.append({"timestamp": timestamp, "close": str(close), "volume": str(volume)})
    return tuple(parsed)


class AlpacaReadClient:
    def __init__(self, http: AsyncJsonClient, key: str, secret: str) -> None:
        self.http = http
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    async def asset(self, symbol: str, now: datetime) -> JsonObject:
        payload, _, _ = await self.http.get_json(
            f"https://paper-api.alpaca.markets/v2/assets/{symbol}",
            operation="asset",
            params={"symbol": symbol},
            headers=self._headers,
            ttl=timedelta(hours=12),
            now=now,
        )
        if not isinstance(payload, dict):
            raise ProviderError("Alpaca asset response is invalid")
        return parse_asset(payload)

    async def snapshot(self, symbol: str, now: datetime) -> JsonObject:
        payload, _, _ = await self.http.get_json(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot",
            operation="snapshot",
            params={"feed": "iex"},
            headers=self._headers,
            ttl=timedelta(minutes=1),
            now=now,
        )
        if not isinstance(payload, dict):
            raise ProviderError("Alpaca snapshot response is invalid")
        return parse_snapshot(payload)

    async def calendar(self, start: date, end: date, now: datetime) -> tuple[date, ...]:
        payload, _, _ = await self.http.get_json(
            "https://paper-api.alpaca.markets/v2/calendar",
            operation="calendar",
            params={"start": start.isoformat(), "end": end.isoformat()},
            headers=self._headers,
            ttl=timedelta(hours=12),
            now=now,
        )
        return parse_calendar(payload)

    async def news(self, symbol: str, now: datetime) -> tuple[JsonObject, ...]:
        payload, _, _ = await self.http.get_json(
            "https://data.alpaca.markets/v1beta1/news",
            operation="news",
            params={"symbols": symbol, "limit": "20"},
            headers=self._headers,
            ttl=timedelta(minutes=15),
            now=now,
        )
        if not isinstance(payload, dict):
            raise ProviderError("Alpaca news response is invalid")
        return parse_news(payload)

    async def bars(
        self, symbol: str, start: date, end: date, now: datetime
    ) -> tuple[JsonObject, ...]:
        payload, _, _ = await self.http.get_json(
            "https://data.alpaca.markets/v2/stocks/bars",
            operation="daily_bars",
            params={
                "symbols": symbol,
                "timeframe": "1Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "all",
                "feed": "iex",
                "limit": "10000",
            },
            headers=self._headers,
            ttl=timedelta(hours=12),
            now=now,
            cache_params={
                "symbol": symbol,
                "period": f"{start.isoformat()}:{end.isoformat()}",
            },
        )
        if not isinstance(payload, dict):
            raise ProviderError("Alpaca bars response is invalid")
        return parse_bars(payload, symbol)
