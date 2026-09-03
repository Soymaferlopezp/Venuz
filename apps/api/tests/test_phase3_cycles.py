import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.domain.paper_execution import (
    CycleState,
    InvalidTransition,
    PreflightInput,
    assert_transition,
    cycle_key,
    evaluate_preflight,
    protection_prices,
)
from app.services.cycles import CycleService, MemoryCycleRepository

NOW = datetime(2026, 9, 3, 14, tzinfo=UTC)


def valid_preflight(**overrides: object) -> PreflightInput:
    values: dict[str, object] = {
        "market_open": True,
        "regular_session": True,
        "data_fresh": True,
        "data_coherent": True,
        "company_eligible": True,
        "criteria_passed": True,
        "valuation_eligible": True,
        "outside_earnings_block": True,
        "quote_fresh": True,
        "spread_pct": Decimal("0.001"),
        "price_drift_pct": Decimal("0.002"),
        "buying_power": Decimal("50000"),
        "order_notional": Decimal("10000"),
        "portfolio_equity": Decimal("100000"),
        "cash": Decimal("50000"),
        "current_position_value": Decimal("0"),
        "current_sector_value": Decimal("5000"),
        "sector_company_count": 1,
    }
    values.update(overrides)
    return PreflightInput.model_validate(values)


@pytest.mark.anyio
async def test_one_hundred_concurrent_activations_create_one_cycle() -> None:
    repository = MemoryCycleRepository()
    service = CycleService(repository, "2026.09")
    cycles = await asyncio.gather(*(service.activate(NOW) for _ in range(100)))
    assert len({cycle.cycle_id for cycle in cycles}) == 1


@pytest.mark.anyio
async def test_retries_and_restart_use_deterministic_cycle_and_order_keys() -> None:
    first = await CycleService(MemoryCycleRepository(), "2026.09").activate(NOW)
    second = await CycleService(MemoryCycleRepository(), "2026.09").activate(NOW)
    assert first.cycle_id == second.cycle_id
    assert cycle_key("2026.09", date(2026, 9, 3), NOW.replace(hour=0)) == first.cycle_key


@pytest.mark.anyio
async def test_completed_cycle_is_returned_as_historical() -> None:
    repository = MemoryCycleRepository()
    cycle = await repository.activate("v:2026-09-03:2026-09-03T00:00:00+00:00", NOW)
    await repository.transition(cycle.cycle_id, CycleState.EXPLORING, NOW, "Exploring")
    await repository.transition(cycle.cycle_id, CycleState.ANALYZING, NOW, "Analyzing")
    await repository.transition(cycle.cycle_id, CycleState.EVALUATING_TRADE, NOW, "Evaluating")
    await repository.transition(cycle.cycle_id, CycleState.COMPLETED, NOW, "No eligible trade")
    latest = await repository.latest()
    assert latest is not None and latest.historical and latest.state == CycleState.COMPLETED


@pytest.mark.anyio
async def test_empty_latest_and_invalid_transition_fail_safely() -> None:
    repository = MemoryCycleRepository()
    assert await repository.latest() is None
    cycle = await repository.activate("v:2026-09-03:cutoff", NOW)
    with pytest.raises(InvalidTransition):
        await repository.transition(cycle.cycle_id, CycleState.COMPLETED, NOW, "invalid")
    with pytest.raises(InvalidTransition):
        assert_transition(CycleState.COMPLETED, CycleState.EXPLORING)


@pytest.mark.parametrize(
    ("overrides", "blocked_guard"),
    [
        ({"market_open": False}, "regular_market_open"),
        ({"data_coherent": False}, "data_sufficient"),
        ({"company_eligible": False}, "company_eligible"),
        ({"criteria_passed": False}, "criteria_passed"),
        ({"valuation_eligible": False}, "valuation_margin"),
        ({"outside_earnings_block": False}, "earnings_window"),
        ({"spread_pct": Decimal("0.02")}, "liquidity_and_spread"),
        ({"price_drift_pct": Decimal("0.02")}, "price_drift"),
        ({"buying_power": Decimal("1")}, "buying_power"),
        ({"cash": Decimal("25000")}, "minimum_cash"),
        ({"current_position_value": Decimal("1")}, "position_cap"),
        ({"current_sector_value": Decimal("11000")}, "sector_cap"),
        ({"sector_company_count": 2}, "sector_company_cap"),
        ({"duplicate_order": True}, "no_duplicate"),
    ],
)
def test_every_preflight_guard_blocks(overrides: dict[str, object], blocked_guard: str) -> None:
    decision = evaluate_preflight(valid_preflight(**overrides))
    assert not decision.eligible
    assert next(item for item in decision.guards if item.code == blocked_guard).reason.endswith(
        "_blocked"
    )


def test_valid_preflight_and_fill_based_protection() -> None:
    decision = evaluate_preflight(valid_preflight())
    assert decision.eligible and all(guard.passed for guard in decision.guards)
    assert protection_prices(Decimal("100")) == (Decimal("90.00"), Decimal("120.00"))


def test_all_states_and_progression_contract_are_explicit() -> None:
    assert {state.value for state in CycleState} == {
        "queued",
        "exploring",
        "analyzing",
        "evaluating_trade",
        "paper_order_submitted",
        "monitoring",
        "completed",
        "blocked",
        "quota_exhausted",
        "provider_unavailable",
        "failed_safe",
    }
