from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from alpaca.data.enums import OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.trading.client import TradingClient

from app.integrations.alpaca_options import (
    AlpacaOptionsGateway,
    _contracts,
    _decimal,
)

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


class TradingStub:
    _base_url = "https://paper-api.alpaca.markets"

    def __init__(self, *, level: int = 1, fail_contracts: bool = False) -> None:
        self.level = level
        self.fail_contracts = fail_contracts

    def get_account(self) -> object:
        return SimpleNamespace(
            options_approved_level=self.level,
            options_trading_level=self.level,
            options_buying_power="10000",
        )

    def get_option_contracts(self, request: object) -> object:
        assert request is not None
        if self.fail_contracts:
            raise RuntimeError
        return SimpleNamespace(
            option_contracts=[
                SimpleNamespace(symbol="AAPL261003P00030000", underlying_symbol="AAPL")
            ]
        )

    def get_all_positions(self) -> list[object]:
        return [
            SimpleNamespace(
                asset_class="us_option",
                symbol="AAPL261003P00030000",
                qty="1",
                avg_entry_price="1.25",
            ),
            SimpleNamespace(asset_class="us_equity", symbol="AAPL", qty="2", avg_entry_price="30"),
            SimpleNamespace(
                asset_class="us_option", symbol="BROKEN", qty=None, avg_entry_price=None
            ),
        ]


class OptionDataStub:
    def __init__(self, opra_fails: bool = False) -> None:
        self.opra_fails = opra_fails
        self.feeds: list[object] = []

    def get_option_chain(self, request: Any) -> object:
        self.feeds.append(request.feed)
        if self.opra_fails and request.feed == OptionsFeed.OPRA:
            raise PermissionError
        return {"AAPL261003P00030000": object()}

    def get_option_snapshot(self, request: Any) -> object:
        return {"AAPL261003P00030000": object()}


def gateway(
    client: httpx.AsyncClient,
    *,
    level: int = 1,
    fail_contracts: bool = False,
    opra_fails: bool = False,
) -> AlpacaOptionsGateway:
    return AlpacaOptionsGateway(
        cast(TradingClient, TradingStub(level=level, fail_contracts=fail_contracts)),
        cast(OptionHistoricalDataClient, OptionDataStub(opra_fails=opra_fails)),
        client,
        "test-key-not-real",
        "test-secret-not-real",
    )


def test_safe_conversion_helpers() -> None:
    assert _decimal("1.25") == Decimal("1.25")
    assert _decimal(None) is None and _decimal("not-a-number") is None
    assert _decimal("Infinity") is None
    assert len(_contracts({"option_contracts": [1]})) == 1
    assert _contracts({"option_contracts": "bad"}) == ()
    assert not _contracts(object())


def test_live_endpoint_is_rejected() -> None:
    trading = TradingStub()
    trading._base_url = "https://api.alpaca.markets"
    with pytest.raises(ValueError, match="Paper"):
        AlpacaOptionsGateway(
            cast(TradingClient, trading),
            cast(OptionHistoricalDataClient, OptionDataStub()),
            cast(httpx.AsyncClient, object()),
            "x",
            "y",
        )


@pytest.mark.anyio
async def test_capability_checks_real_surfaces_and_feed_fallback() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        target = gateway(client, opra_fails=True)
        result = await target.capability()
    assert result.status == "available"
    assert result.feed is not None and result.feed.value == "indicative"
    assert result.contracts_accessible and result.chains_accessible and result.snapshots_accessible


@pytest.mark.anyio
async def test_capability_distinguishes_level_one_block_from_unavailable_access() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        blocked = await gateway(client, level=0).capability()
        unavailable = await gateway(client, fail_contracts=True).capability()
    assert blocked.status == "blocked"
    assert "options_approved_level_1_required" in blocked.blocking_reasons
    assert unavailable.status == "unavailable"
    assert unavailable.blocking_reasons == ("option_contracts_unavailable",)


@pytest.mark.anyio
async def test_positions_are_option_only_and_sanitized() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        positions = await gateway(client).option_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL261003P00030000" and positions[0].quantity == Decimal("1")


@pytest.mark.anyio
async def test_option_activities_accept_only_supported_events() -> None:
    payload = [
        {
            "id": "a1",
            "activity_type": "OPASN",
            "symbol": "AAPL261003P00030000",
            "qty": "1",
            "price": "30",
            "transaction_time": "2026-09-04T12:00:00Z",
        },
        {
            "id": "a2",
            "activity_type": "OPEXP",
            "symbol": "AAPL261003P00030000",
            "date": "2026-10-03T00:00:00Z",
        },
        {"id": "ignored", "activity_type": "FILL", "symbol": "AAPL"},
        "invalid",
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        activities = await gateway(client).option_activities(NOW)
    assert [item.activity_type for item in activities] == ["OPASN", "OPEXP"]
    assert seen and seen[0].url.host == "paper-api.alpaca.markets"
    assert seen[0].url.params["activity_types"] == "OPASN,OPTRD,OPEXP"


@pytest.mark.anyio
async def test_invalid_activity_payload_fails_closed() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(RuntimeError, match="Invalid"):
            await gateway(client).option_activities(NOW)


class RemoteStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__("sensitive upstream detail must not escape")
        self.status_code = status_code


class AccountFailureTrading(TradingStub):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def get_account(self) -> object:
        raise self.error


class IncompleteAccountTrading(TradingStub):
    def get_account(self) -> object:
        return SimpleNamespace(options_approved_level=1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (TimeoutError("private timeout detail"), "alpaca_account_timeout"),
        (RemoteStatusError(401), "alpaca_account_unauthorized"),
        (RemoteStatusError(403), "alpaca_account_unauthorized"),
        (RemoteStatusError(429), "alpaca_account_rate_limited"),
        (RemoteStatusError(503), "alpaca_account_unavailable"),
    ),
)
async def test_capability_remote_failures_are_unavailable_and_sanitized(
    error: BaseException, reason: str
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        target = AlpacaOptionsGateway(
            cast(TradingClient, AccountFailureTrading(error)),
            cast(OptionHistoricalDataClient, OptionDataStub()),
            client,
            "test-key-not-real",
            "test-secret-not-real",
        )
        result = await target.capability()
    assert result.status == "unavailable"
    assert result.blocking_reasons == (reason,)
    serialized = result.model_dump_json()
    assert "private timeout detail" not in serialized
    assert "sensitive upstream detail" not in serialized
    assert "paper-api.alpaca.markets" not in serialized


@pytest.mark.anyio
async def test_capability_incomplete_account_payload_is_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        target = AlpacaOptionsGateway(
            cast(TradingClient, IncompleteAccountTrading()),
            cast(OptionHistoricalDataClient, OptionDataStub()),
            client,
            "test-key-not-real",
            "test-secret-not-real",
        )
        result = await target.capability()
    assert result.status == "unavailable"
    assert result.blocking_reasons == ("alpaca_account_payload_invalid",)
    assert result.options_trading_level is None


class InvalidContractsPayloadTrading(TradingStub):
    def get_option_contracts(self, request: object) -> object:
        assert request is not None
        return {"unexpected": "private payload"}


@pytest.mark.anyio
async def test_capability_invalid_contract_payload_is_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        target = AlpacaOptionsGateway(
            cast(TradingClient, InvalidContractsPayloadTrading()),
            cast(OptionHistoricalDataClient, OptionDataStub()),
            client,
            "test-key-not-real",
            "test-secret-not-real",
        )
        result = await target.capability()
    assert result.status == "unavailable"
    assert result.blocking_reasons == ("option_contract_payload_invalid",)
    assert "private payload" not in result.model_dump_json()
