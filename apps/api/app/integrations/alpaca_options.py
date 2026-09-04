from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from alpaca.data.enums import OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionSnapshotRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, ContractType
from alpaca.trading.requests import GetOptionContractsRequest
from pydantic import BaseModel, ConfigDict

from app.core.config import PAPER_TRADING_URL
from app.domain.options import OptionFeed, OptionsCapability


class OptionRemotePosition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    asset_class: str


class OptionAccountActivity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    activity_id: str
    activity_type: str
    symbol: str | None
    quantity: Decimal | None
    price: Decimal | None
    occurred_at: datetime
    underlying: str | None = None


class OptionsGateway(Protocol):
    async def capability(self) -> OptionsCapability: ...
    async def option_positions(self) -> tuple[OptionRemotePosition, ...]: ...
    async def option_activities(self, after: datetime) -> tuple[OptionAccountActivity, ...]: ...


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _level(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and 0 <= result <= 3 else None


def _capability_failure_reason(error: BaseException, surface: str) -> str:
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        return f"{surface}_timeout"
    status = getattr(error, "status_code", None)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    if status in {401, 403}:
        return f"{surface}_unauthorized"
    if status == 429:
        return f"{surface}_rate_limited"
    return f"{surface}_unavailable"


def _contracts_payload_valid(response: object) -> bool:
    if isinstance(response, Mapping):
        value = response.get("option_contracts")
    else:
        value = getattr(response, "option_contracts", None)
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _contracts(response: object) -> Sequence[Any]:
    if isinstance(response, Mapping):
        value = response.get("option_contracts", [])
    else:
        value = getattr(response, "option_contracts", [])
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


class AlpacaOptionsGateway:
    """Read-only capability/data surface for an exact Alpaca Paper account."""

    def __init__(
        self,
        trading: TradingClient,
        option_data: OptionHistoricalDataClient,
        http: httpx.AsyncClient,
        api_key: str,
        secret_key: str,
    ) -> None:
        if urlsplit(str(trading._base_url)).hostname != "paper-api.alpaca.markets":
            raise ValueError("Options gateway requires the Alpaca Paper endpoint")
        self.trading = trading
        self.option_data = option_data
        self.http = http
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}

    async def capability(self) -> OptionsCapability:
        checked_at = datetime.now(UTC)
        try:
            account = await asyncio.to_thread(self.trading.get_account)
        except Exception as error:
            return OptionsCapability(
                status="unavailable",
                paper_endpoint_valid=True,
                checked_at=checked_at,
                blocking_reasons=(_capability_failure_reason(error, "alpaca_account"),),
            )
        approved = _level(getattr(account, "options_approved_level", None))
        trading_level = _level(getattr(account, "options_trading_level", None))
        buying_power = _decimal(getattr(account, "options_buying_power", None))
        if approved is None or trading_level is None or buying_power is None:
            return OptionsCapability(
                status="unavailable",
                options_approved_level=approved,
                options_trading_level=trading_level,
                options_buying_power_available=buying_power is not None,
                paper_endpoint_valid=True,
                checked_at=checked_at,
                blocking_reasons=("alpaca_account_payload_invalid",),
            )

        level_reasons: list[str] = []
        if approved < 1:
            level_reasons.append("options_approved_level_1_required")
        if trading_level < 1:
            level_reasons.append("options_trading_level_1_required")

        contracts_accessible = chains_accessible = snapshots_accessible = False
        option_assets_available = False
        selected_feed: OptionFeed | None = None
        try:
            response = await asyncio.to_thread(
                self.trading.get_option_contracts,
                GetOptionContractsRequest(
                    status=AssetStatus.ACTIVE,
                    type=ContractType.PUT,
                    expiration_date_gte=checked_at.date(),
                    limit=1,
                ),
            )
            if not _contracts_payload_valid(response):
                return OptionsCapability(
                    status="unavailable",
                    options_approved_level=approved,
                    options_trading_level=trading_level,
                    options_buying_power_available=True,
                    paper_endpoint_valid=True,
                    checked_at=checked_at,
                    blocking_reasons=("option_contract_payload_invalid",),
                )
            contracts_accessible = True
            contracts = _contracts(response)
            option_assets_available = bool(contracts)
            if contracts:
                contract = contracts[0]
                symbol = str(getattr(contract, "symbol", ""))
                underlying = str(getattr(contract, "underlying_symbol", ""))
                if not symbol or not underlying:
                    return OptionsCapability(
                        status="unavailable",
                        options_approved_level=approved,
                        options_trading_level=trading_level,
                        options_buying_power_available=True,
                        paper_endpoint_valid=True,
                        contracts_accessible=True,
                        checked_at=checked_at,
                        blocking_reasons=("option_contract_payload_invalid",),
                    )
                selected_feed, chains_accessible, snapshots_accessible = await self._probe_data(
                    underlying, symbol
                )
        except Exception as error:
            return OptionsCapability(
                status="unavailable",
                options_approved_level=approved,
                options_trading_level=trading_level,
                options_buying_power_available=True,
                paper_endpoint_valid=True,
                checked_at=checked_at,
                blocking_reasons=(_capability_failure_reason(error, "option_contracts"),),
            )

        availability_reasons: list[str] = []
        if not option_assets_available:
            availability_reasons.append("no_active_option_contract_available")
        if not chains_accessible:
            availability_reasons.append("option_chain_unavailable")
        if not snapshots_accessible:
            availability_reasons.append("option_snapshot_unavailable")
        if selected_feed is None:
            availability_reasons.append("options_feed_unavailable")
        reasons = level_reasons + availability_reasons
        status = (
            "unavailable" if availability_reasons else "blocked" if level_reasons else "available"
        )
        return OptionsCapability(
            status=status,
            options_approved_level=approved,
            options_trading_level=trading_level,
            options_buying_power_available=True,
            paper_endpoint_valid=True,
            option_assets_available=option_assets_available,
            contracts_accessible=contracts_accessible,
            chains_accessible=chains_accessible,
            snapshots_accessible=snapshots_accessible,
            feed=selected_feed,
            checked_at=checked_at,
            blocking_reasons=tuple(dict.fromkeys(reasons)),
        )

    async def _probe_data(
        self, underlying: str, contract_symbol: str
    ) -> tuple[OptionFeed | None, bool, bool]:
        for sdk_feed, domain_feed in (
            (OptionsFeed.OPRA, OptionFeed.OPRA),
            (OptionsFeed.INDICATIVE, OptionFeed.INDICATIVE),
        ):
            try:
                chain = await asyncio.to_thread(
                    self.option_data.get_option_chain,
                    OptionChainRequest(
                        underlying_symbol=underlying,
                        feed=sdk_feed,
                        type=ContractType.PUT,
                    ),
                )
                snapshot = await asyncio.to_thread(
                    self.option_data.get_option_snapshot,
                    OptionSnapshotRequest(symbol_or_symbols=[contract_symbol], feed=sdk_feed),
                )
                if isinstance(chain, Mapping) and isinstance(snapshot, Mapping):
                    return domain_feed, True, True
            except Exception:
                continue
        return None, False, False

    async def option_positions(self) -> tuple[OptionRemotePosition, ...]:
        positions = await asyncio.to_thread(self.trading.get_all_positions)
        result: list[OptionRemotePosition] = []
        for item in positions:
            asset_class = str(getattr(item, "asset_class", "")).lower()
            if "option" not in asset_class:
                continue
            quantity = _decimal(getattr(item, "qty", None))
            average = _decimal(getattr(item, "avg_entry_price", None))
            symbol = str(getattr(item, "symbol", ""))
            if not symbol or quantity is None or average is None:
                continue
            result.append(
                OptionRemotePosition(
                    symbol=symbol,
                    quantity=quantity,
                    average_entry_price=average,
                    asset_class="option",
                )
            )
        return tuple(result)

    async def option_activities(self, after: datetime) -> tuple[OptionAccountActivity, ...]:
        response = await self.http.get(
            f"{PAPER_TRADING_URL}/v2/account/activities",
            headers=self._headers,
            params={
                "activity_types": "OPASN,OPTRD,OPEXP",
                "after": after.astimezone(UTC).isoformat(),
                "direction": "asc",
                "page_size": "100",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Invalid Alpaca options activity response")
        activities: list[OptionAccountActivity] = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            activity_type = str(row.get("activity_type", ""))
            if activity_type not in {"OPASN", "OPTRD", "OPEXP"}:
                continue
            occurred = row.get("transaction_time") or row.get("date")
            if occurred is None:
                continue
            activities.append(
                OptionAccountActivity(
                    activity_id=str(row.get("id", "")),
                    activity_type=activity_type,
                    symbol=str(row["symbol"]) if row.get("symbol") else None,
                    underlying=(
                        str(row["underlying_symbol"]) if row.get("underlying_symbol") else None
                    ),
                    quantity=_decimal(row.get("qty")),
                    price=_decimal(row.get("price")),
                    occurred_at=datetime.fromisoformat(str(occurred).replace("Z", "+00:00")),
                )
            )
        return tuple(activities)
