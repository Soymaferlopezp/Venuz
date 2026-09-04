from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.options import (
    CycleMode,
    OptionCandidate,
    OptionEvaluation,
    OptionFeed,
    OptionPortfolio,
    OptionsCapability,
    evaluate_option_candidate,
)
from app.domain.options_lifecycle import OptionPositionStatus, OptionSettlementEvent
from app.integrations.alpaca_broker import AlpacaPyBroker
from app.integrations.alpaca_options import OptionAccountActivity
from app.integrations.broker import AmbiguousBrokerResult, BrokerOrderCommand, BrokerOrderKind
from app.repositories.options import MemoryOptionRepository
from app.services.options import OptionsService, UnsafeOptionTransition
from app.services.options_explanation import OptionExplanationService
from tests.fakes.broker import FakeBroker
from tests.fakes.options import FakeOptionsGateway

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


def valid_evaluation() -> tuple[OptionEvaluation, OptionPortfolio]:
    candidate = OptionCandidate(
        occ_symbol="AAPL261003P00030000",
        underlying="AAPL",
        underlying_kind="equity",
        sector="Technology",
        contract_type="put",
        position_intent="sell_to_open",
        contracts=1,
        tradable=True,
        optionable=True,
        expiration=date(2026, 10, 3),
        strike=Decimal("30"),
        delta=Decimal("-0.22"),
        bid=Decimal("1"),
        ask=Decimal("1.10"),
        quote_at=NOW,
        volume=500,
        open_interest=1000,
        implied_volatility=Decimal("0.30"),
        realized_volatility=Decimal("0.20"),
        realized_volatility_window=20,
        feed=OptionFeed.INDICATIVE,
        underlying_price=Decimal("35"),
        underlying_quote_at=NOW,
        underlying_dollar_volume=Decimal("100000000"),
        price_drift_pct=Decimal("0.001"),
        company_eligible=True,
        earnings_window_clear=True,
        options_market_open=True,
        observed_at=NOW,
    )
    portfolio = OptionPortfolio(
        equity=Decimal("100000"),
        cash=Decimal("50000"),
        options_buying_power=Decimal("50000"),
        current_position_assignment_exposure=Decimal("0"),
        current_sector_assignment_exposure=Decimal("0"),
        sector_company_count=0,
    )
    capability = OptionsCapability(
        status="available",
        options_approved_level=1,
        options_trading_level=1,
        options_buying_power_available=True,
        paper_endpoint_valid=True,
        option_assets_available=True,
        contracts_accessible=True,
        chains_accessible=True,
        snapshots_accessible=True,
        feed=OptionFeed.INDICATIVE,
        checked_at=NOW,
    )
    return evaluate_option_candidate(
        candidate, portfolio, capability, CycleMode.OPTIONS, NOW
    ), portfolio


def service() -> tuple[OptionsService, MemoryOptionRepository, FakeBroker, FakeOptionsGateway]:
    repository = MemoryOptionRepository()
    broker = FakeBroker()
    gateway = FakeOptionsGateway()
    return OptionsService(repository, broker, gateway), repository, broker, gateway


@pytest.mark.anyio
async def test_submission_is_durable_idempotent_and_concurrent() -> None:
    target, repository, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    first, second = await asyncio.gather(
        target.submit_entry("cycle-1", evaluation, portfolio, NOW),
        target.submit_entry("cycle-1", evaluation, portfolio, NOW),
    )
    assert first.client_order_id == second.client_order_id
    assert (
        len({command.client_order_id for command in broker.commands}) == 1
        and len(repository.collateral) == 1
    )


@pytest.mark.anyio
async def test_partial_then_full_fill_opens_only_after_real_full_fill() -> None:
    target, repository, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    order = await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    broker.fill(order.client_order_id, Decimal("0.5"), Decimal("1"))
    partial = await target.reconcile_entry(order.intent_key, evaluation)
    assert partial.filled_quantity == Decimal("0.5") and not repository.positions
    broker.fill(order.client_order_id, Decimal("1"), Decimal("1"))
    filled = await target.reconcile_entry(order.intent_key, evaluation)
    position = await repository.position_by_contract(evaluation.candidate.occ_symbol, "cycle-1")
    assert filled.status.value == "filled"
    assert position is not None and position.entry_credit_total == Decimal("100.00")


@pytest.mark.anyio
async def test_ambiguous_timeout_never_duplicates_contract() -> None:
    target, _, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    broker.ambiguous_next_submit = True
    with pytest.raises(AmbiguousBrokerResult):
        await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    assert len({command.client_order_id for command in broker.commands}) == 1


@pytest.mark.anyio
async def test_ambiguous_persisted_response_is_recovered() -> None:
    target, _, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    broker.persist_ambiguous_submit = True
    order = await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    assert order.status.value == "submitted" and len(broker.commands) == 1


@pytest.mark.anyio
async def test_lookup_ambiguity_is_audited() -> None:
    target, repository, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    broker.ambiguous_next_lookup = True
    with pytest.raises(AmbiguousBrokerResult):
        await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    assert any(
        event.event_type == "option.order.lookup_ambiguous" for event in repository.events.values()
    )


@pytest.mark.anyio
async def test_automatic_execution_defaults_off_and_preflight_cannot_be_skipped() -> None:
    target, _, _, _ = service()
    evaluation, portfolio = valid_evaluation()
    with pytest.raises(UnsafeOptionTransition, match="disabled"):
        await target.submit_automatic_entry("cycle-1", evaluation, portfolio, NOW)
    unsafe = evaluation.model_copy(update={"eligible": False})
    enabled, _, _, _ = service()
    enabled.auto_execution_enabled = True
    with pytest.raises(UnsafeOptionTransition, match="preflight"):
        await enabled.submit_automatic_entry("cycle-1", unsafe, portfolio, NOW)


async def opened_position() -> tuple[OptionsService, MemoryOptionRepository, FakeBroker, str]:
    target, repository, broker, _ = service()
    evaluation, portfolio = valid_evaluation()
    order = await target.submit_entry("cycle-1", evaluation, portfolio, NOW)
    broker.fill(order.client_order_id, Decimal("1"), Decimal("1"))
    await target.reconcile_entry(order.intent_key, evaluation)
    position = await repository.position_by_contract(evaluation.candidate.occ_symbol, "cycle-1")
    assert position is not None
    return target, repository, broker, position.position_id


@pytest.mark.anyio
async def test_take_profit_close_and_no_overlapping_close() -> None:
    target, repository, broker, position_id = await opened_position()
    close = await target.close_if_required(position_id, Decimal("0.50"), 30, now=NOW)
    duplicate = await target.close_if_required(position_id, Decimal("0.50"), 30, now=NOW)
    assert close is not None and duplicate == close
    assert (
        len([command for command in broker.commands if command.position_intent == "buy_to_close"])
        == 1
    )
    broker.fill(close.client_order_id, Decimal("1"), Decimal("0.50"))
    await target.close_if_required(position_id, Decimal("0.50"), 30, now=NOW)
    position = await repository.position(position_id)
    assert position is not None and position.status == OptionPositionStatus.CLOSED


@pytest.mark.anyio
async def test_replacement_requires_confirmed_cancel_and_stop_has_priority() -> None:
    target, _, broker, position_id = await opened_position()
    take_profit = await target.close_if_required(position_id, Decimal("0.50"), 30, now=NOW)
    assert take_profit is not None
    stop = await target.close_if_required(
        position_id, Decimal("3"), 30, now=NOW + timedelta(seconds=1)
    )
    assert stop is not None and stop.intent_key != take_profit.intent_key
    assert broker.cancelled == [take_profit.broker_order_id]


@pytest.mark.anyio
async def test_no_exit_before_threshold_and_21_dte_exit() -> None:
    target, repository, _, position_id = await opened_position()
    assert await target.close_if_required(position_id, Decimal("0.51"), 30, now=NOW) is None
    close = await target.close_if_required(position_id, Decimal("1"), 21, now=NOW)
    assert close is not None and ":dte_21:" in close.intent_key


@pytest.mark.anyio
async def test_assignment_and_expiration_are_idempotent_and_release_collateral() -> None:
    target, repository, _, position_id = await opened_position()
    assignment = OptionAccountActivity(
        activity_id="activity-1",
        activity_type="OPASN",
        symbol="AAPL261003P00030000",
        quantity=Decimal("1"),
        price=Decimal("3000"),
        occurred_at=NOW + timedelta(days=1),
    )
    first = await target.process_activity("cycle-1", assignment)
    second = await target.process_activity("cycle-1", assignment)
    assert first is not None and second is None and first.shares == 100
    assert repository.assigned_shares == {"AAPL": 100}
    position = await repository.position(position_id)
    assert position is not None and position.status == OptionPositionStatus.ASSIGNED
    assert all(item.status.value == "released" for item in repository.collateral.values())

    target2, repository2, _, position_id2 = await opened_position()
    expiry = assignment.model_copy(
        update={"activity_id": "activity-2", "activity_type": "OPEXP", "price": None}
    )
    event = await target2.process_activity("cycle-1", expiry)
    position2 = await repository2.position(position_id2)
    assert event is not None and event.shares == 0
    assert position2 is not None and position2.status == OptionPositionStatus.EXPIRED


@pytest.mark.anyio
async def test_restart_queries_positions_and_processes_optrd() -> None:
    target, repository, _, position_id = await opened_position()
    gateway = target.gateway
    assert isinstance(gateway, FakeOptionsGateway)
    gateway.activities = (
        OptionAccountActivity(
            activity_id="trade-1",
            activity_type="OPTRD",
            symbol="AAPL261003P00030000",
            quantity=Decimal("1"),
            price=Decimal("30"),
            occurred_at=NOW + timedelta(days=1),
        ),
    )
    processed = await target.reconcile_after_restart("cycle-1", NOW)
    assert processed and processed[0].shares == 100 and position_id
    assert repository.assigned_shares == {"AAPL": 100}


class FailingGateway(FakeOptionsGateway):
    async def capability(self) -> OptionsCapability:
        raise TimeoutError


@pytest.mark.anyio
async def test_capability_failure_blocks_safely_without_account_values() -> None:
    repository = MemoryOptionRepository()
    result = await OptionsService(repository, FakeBroker(), FailingGateway()).capability()
    assert result.status == "unavailable" and result.options_approved_level is None


class Provider:
    def __init__(self, value: str = "narrative", fail: bool = False) -> None:
        self.value = value
        self.fail = fail

    async def explain(self, payload: dict[str, object]) -> str:
        if self.fail:
            raise RuntimeError
        assert "eligible" in payload
        return self.value


@pytest.mark.anyio
async def test_llm_only_changes_narrative_and_structured_fallback_survives() -> None:
    evaluation, _ = valid_evaluation()
    explained = await OptionExplanationService(Provider()).explain(evaluation)
    assert explained.eligible == evaluation.eligible and explained.generated_by == "gemini"
    fallback = await OptionExplanationService(Provider(fail=True), Provider(fail=True)).explain(
        evaluation
    )
    assert (
        fallback.generated_by == "deterministic_code"
        and fallback.contract == evaluation.candidate.occ_symbol
    )


def test_broker_option_request_uses_real_sdk_position_intent_and_market_day() -> None:
    command = BrokerOrderCommand(
        client_order_id="options-test",
        symbol="AAPL261003P00030000",
        side="sell",
        kind=BrokerOrderKind.MARKET,
        quantity=Decimal("1"),
        asset_class="option",
        position_intent="sell_to_open",
    )
    request = AlpacaPyBroker._request(command)
    assert str(request.position_intent).lower().endswith("sell_to_open")
    assert str(request.time_in_force).lower().endswith("day")


@pytest.mark.anyio
@pytest.mark.parametrize("first_type", ("OPASN", "OPTRD"))
async def test_opasn_and_optrd_share_economic_assignment_but_keep_both_audits(
    first_type: str,
) -> None:
    target, repository, _, _ = await opened_position()
    second_type = "OPTRD" if first_type == "OPASN" else "OPASN"

    def activity(activity_type: str) -> OptionAccountActivity:
        return OptionAccountActivity(
            activity_id="shared-activity-id",
            activity_type=activity_type,
            symbol="AAPL261003P00030000",
            underlying="AAPL",
            quantity=Decimal("1"),
            price=Decimal("30"),
            occurred_at=NOW + timedelta(days=1),
        )

    first = await target.process_activity("cycle-1", activity(first_type))
    restarted = OptionsService(repository, FakeBroker(), FakeOptionsGateway())
    second = await restarted.process_activity("cycle-1", activity(second_type))
    first_duplicate = await restarted.process_activity("cycle-1", activity(first_type))
    second_duplicate = await restarted.process_activity("cycle-1", activity(second_type))

    assert first is not None and second is not None
    assert first_duplicate is None and second_duplicate is None
    assert len(repository.settlements) == 2
    assert {item.activity_type for item in repository.settlements.values()} == {"OPASN", "OPTRD"}
    assert repository.assigned_shares == {"AAPL": 100}
    audited = {item.event_type for item in repository.events.values()}
    assert "option.activity.opasn" in audited and "option.activity.optrd" in audited


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"underlying": "MSFT"}, "underlying"),
        ({"quantity": Decimal("2")}, "exactly one contract"),
        ({"activity_type": "UNKNOWN"}, "Unsupported"),
    ),
)
async def test_settlement_rejects_inconsistent_activity_without_mutation(
    updates: dict[str, object], message: str
) -> None:
    target, repository, _, position_id = await opened_position()
    activity = OptionAccountActivity(
        activity_id="invalid-activity",
        activity_type="OPASN",
        symbol="AAPL261003P00030000",
        underlying="AAPL",
        quantity=Decimal("1"),
        price=Decimal("30"),
        occurred_at=NOW + timedelta(days=1),
    ).model_copy(update=updates)
    with pytest.raises(UnsafeOptionTransition, match=message):
        await target.process_activity("cycle-1", activity)
    position = await repository.position(position_id)
    assert position is not None and position.status == OptionPositionStatus.OPEN
    assert repository.assigned_shares == {}
    assert all(item.status.value == "consumed" for item in repository.collateral.values())


@pytest.mark.anyio
async def test_settlement_rejects_cycle_occ_and_share_mismatches_without_mutation() -> None:
    target, repository, _, position_id = await opened_position()
    position = await repository.position(position_id)
    assert position is not None
    base = OptionSettlementEvent(
        activity_id="invalid-direct",
        cycle_id="cycle-1",
        option_position_id=position_id,
        activity_type="OPASN",
        occ_symbol=position.occ_symbol,
        underlying=position.underlying,
        shares=100,
        occurred_at=NOW + timedelta(days=1),
    )
    for event in (
        base.model_copy(update={"cycle_id": "wrong-cycle"}),
        base.model_copy(update={"occ_symbol": "MSFT261003P00030000"}),
        base.model_copy(update={"shares": 0}),
    ):
        with pytest.raises(ValueError, match="invariant"):
            await repository.save_settlement(event)
    current = await repository.position(position_id)
    assert current is not None and current.status == OptionPositionStatus.OPEN
    assert repository.assigned_shares == {} and repository.settlements == {}
