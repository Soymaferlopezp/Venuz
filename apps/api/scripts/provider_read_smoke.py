"""Sanitized, read-only smoke test for the SEC and Alpaca adapters."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings
from app.integrations.alpaca import AlpacaReadClient
from app.integrations.base import AsyncJsonClient, MemoryCacheStore, ProviderError
from app.integrations.sec import SecEdgarClient


async def main() -> None:
    settings = Settings()
    now = datetime.now(UTC)
    cache = MemoryCacheStore()
    async with httpx.AsyncClient() as client:
        sec = SecEdgarClient(
            AsyncJsonClient(provider="sec_edgar", client=client, cache=cache),
            settings.sec_user_agent,
        )
        alpaca = AlpacaReadClient(
            AsyncJsonClient(provider="alpaca", client=client, cache=cache),
            settings.alpaca_api_key.get_secret_value(),
            settings.alpaca_secret_key.get_secret_value(),
        )
        facts, _, _ = await sec.company_facts("0000320193", now)
        submissions, _, _ = await sec.submissions("0000320193", now)
        asset = await alpaca.asset("AAPL", now)
        snapshot = None
        snapshot_rejected_safely = False
        try:
            snapshot = await alpaca.snapshot("AAPL", now)
        except ProviderError:
            snapshot_rejected_safely = True
        sessions = await alpaca.calendar(
            now.date() - timedelta(days=7), now.date() + timedelta(days=7), now
        )
        bars = await alpaca.bars("AAPL", now.date() - timedelta(days=40), now.date(), now)
        news = await alpaca.news("AAPL", now)
    result = {
        "alpaca": {
            "asset_symbol_matches": asset["symbol"] == "AAPL",
            "bars_received": len(bars),
            "calendar_sessions_received": len(sessions),
            "news_received": len(news),
            "snapshot_rejected_safely": snapshot_rejected_safely,
            "snapshot_valid": snapshot is not None
            and all(snapshot.get(key) for key in ("price", "bid", "ask")),
        },
        "orders_sent": 0,
        "sec_edgar": {
            "company_facts_received": isinstance(facts.get("facts"), dict),
            "submissions_received": isinstance(submissions.get("filings"), dict),
        },
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
