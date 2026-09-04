from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.domain.options import OptionEvaluation
from app.domain.options_lifecycle import OptionPositionRecord, OptionPositionStatus
from app.repositories.analysis import SupabaseRestStore
from app.repositories.options import MemoryOptionRepository, SupabaseOptionRepository
from tests.fakes.options import FakeOptionsGateway
from tests.test_phase3b_options_lifecycle import NOW, valid_evaluation


def order_row() -> dict[str, object]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "cycle_id": "cycle-1",
        "option_position_id": None,
        "intent_key": "cycle-1:option:AAPL261003P00030000:sell_to_open:v1",
        "client_order_id": "vz-safe-client-id",
        "symbol": "AAPL261003P00030000",
        "underlying_symbol": "AAPL",
        "position_intent": "sell_to_open",
        "status": "pending",
        "quantity": "1",
        "filled_quantity": "0",
        "average_fill_price": None,
        "broker_order_id": None,
        "observed_at": NOW.isoformat(),
        "reservation_created": True,
    }


@pytest.mark.anyio
async def test_supabase_repository_uses_atomic_entry_rpc_and_sanitized_capability() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "reserve_option_entry" in str(request.url):
            return httpx.Response(200, json=order_row())
        return httpx.Response(201)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseOptionRepository(
            SupabaseRestStore("https://db.example.test", "test-only", client)
        )
        evaluation, portfolio = valid_evaluation()
        await repository.save_capability(FakeOptionsGateway().capability_result)
        order, created = await repository.reserve_entry("cycle-1", evaluation, portfolio, NOW)
    assert created and order.position_intent == "sell_to_open"
    capability_payload = json.loads(requests[0].content)
    assert "buying_power_available" in capability_payload
    assert "options_buying_power" not in capability_payload
    reservation_payload = json.loads(requests[1].content)
    assert reservation_payload["p_collateral"] == "3000.00"
    assert reservation_payload["p_evaluation"]["eligible"] is True


@pytest.mark.anyio
async def test_supabase_repository_fails_closed_on_invalid_rpc_and_empty_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "reserve_option_entry" in str(request.url):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseOptionRepository(
            SupabaseRestStore("https://db.example.test", "test-only", client)
        )
        evaluation, portfolio = valid_evaluation()
        with pytest.raises(RuntimeError, match="entry reservation"):
            await repository.reserve_entry("cycle-1", evaluation, portfolio, NOW)
        snapshot = await repository.cycle_snapshot("missing")
    assert snapshot.cycle_id == "missing" and snapshot.evaluations == ()


@pytest.mark.anyio
async def test_memory_reservation_rechecks_cash_and_cycle_limit() -> None:
    repository = MemoryOptionRepository()
    evaluation, portfolio = valid_evaluation()
    too_little = portfolio.model_copy(update={"cash": Decimal("2999")})
    with pytest.raises(ValueError, match="Cash reserve"):
        await repository.reserve_entry("cycle-1", evaluation, too_little, NOW)
    await repository.reserve_entry("cycle-1", evaluation, portfolio, NOW)
    other = evaluation.model_copy(
        update={
            "candidate": evaluation.candidate.model_copy(
                update={"occ_symbol": "AAPL261003P00029000"}
            )
        }
    )
    with pytest.raises(ValueError, match="at most one"):
        await repository.reserve_entry("cycle-1", other, portfolio, datetime.now(UTC))


def changed_evaluation(
    evaluation: OptionEvaluation, *, underlying: str, occ_symbol: str, sector: str
) -> OptionEvaluation:
    value = evaluation
    return value.model_copy(
        update={
            "candidate": value.candidate.model_copy(
                update={
                    "underlying": underlying,
                    "occ_symbol": occ_symbol,
                    "sector": sector,
                }
            )
        }
    )


@pytest.mark.anyio
async def test_concurrent_reservations_recompute_twenty_percent_cash_floor() -> None:
    repository = MemoryOptionRepository()
    base, portfolio = valid_evaluation()
    portfolio = portfolio.model_copy(update={"cash": Decimal("25000")})
    other = changed_evaluation(
        base,
        underlying="MSFT",
        occ_symbol="MSFT261003P00030000",
        sector="Industrials",
    )
    results = await asyncio.gather(
        repository.reserve_entry("cycle-a", base, portfolio, NOW),
        repository.reserve_entry("cycle-b", other, portfolio, NOW),
        return_exceptions=True,
    )
    assert sum(isinstance(item, ValueError) for item in results) == 1
    assert len(repository.collateral) == 1


@pytest.mark.anyio
async def test_durable_reservation_guards_underlying_sector_and_company_count() -> None:
    base, portfolio = valid_evaluation()

    underlying_repository = MemoryOptionRepository()
    underlying_repository.stock_exposures["AAPL"] = ("Technology", Decimal("8000"))
    with pytest.raises(ValueError, match="Underlying"):
        await underlying_repository.reserve_entry("cycle-underlying", base, portfolio, NOW)

    sector_repository = MemoryOptionRepository()
    sector_repository.stock_exposures["MSFT"] = ("Technology", Decimal("18000"))
    with pytest.raises(ValueError, match="Sector assignment"):
        await sector_repository.reserve_entry("cycle-sector", base, portfolio, NOW)

    company_repository = MemoryOptionRepository()
    company_repository.stock_exposures.update(
        {
            "MSFT": ("Technology", Decimal("1000")),
            "ORCL": ("Technology", Decimal("1000")),
        }
    )
    with pytest.raises(ValueError, match="third company"):
        await company_repository.reserve_entry("cycle-company", base, portfolio, NOW)


@pytest.mark.anyio
async def test_idempotent_retry_and_reserved_to_consumed_do_not_double_count() -> None:
    repository = MemoryOptionRepository()
    evaluation, portfolio = valid_evaluation()
    first, created = await repository.reserve_entry("cycle-a", evaluation, portfolio, NOW)
    retried, retry_created = await repository.reserve_entry("cycle-a", evaluation, portfolio, NOW)
    assert created and not retry_created and first == retried and len(repository.collateral) == 1

    candidate = evaluation.candidate
    await repository.save_position(
        OptionPositionRecord(
            position_id="position-a",
            cycle_id="cycle-a",
            occ_symbol=candidate.occ_symbol,
            underlying=candidate.underlying,
            sector=candidate.sector,
            contracts=1,
            strike=candidate.strike,
            expiration=candidate.expiration,
            entry_credit_per_share=Decimal("1"),
            entry_credit_total=Decimal("100"),
            collateral=evaluation.collateral,
            status=OptionPositionStatus.OPEN,
            opened_at=NOW,
            updated_at=NOW,
        )
    )
    assert next(iter(repository.collateral.values())).status.value == "consumed"

    second = changed_evaluation(
        evaluation,
        underlying="AAPL",
        occ_symbol="AAPL261003P00029000",
        sector="Technology",
    )
    tighter = portfolio.model_copy(update={"equity": Decimal("60000")})
    _, second_created = await repository.reserve_entry("cycle-b", second, tighter, NOW)
    assert second_created and len(repository.collateral) == 2
