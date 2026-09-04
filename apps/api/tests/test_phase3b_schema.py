from pathlib import Path

MIGRATION = (
    Path(__file__).parents[3] / "supabase/migrations/20260903150000_phase3b_options_trading.sql"
)
PGTAP = Path(__file__).parents[3] / "supabase/tests/phase3b_options_rls.test.sql"


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_phase3b_is_a_new_migration_after_applied_phase3() -> None:
    assert MIGRATION.name > "20260903043000_phase3_global_cycles.sql"
    assert MIGRATION.exists()


def test_every_new_sensitive_table_enables_rls_and_denies_public_writes() -> None:
    content = sql()
    tables = (
        "options_capability_checks",
        "option_contract_observations",
        "option_candidate_evaluations",
        "option_positions",
        "collateral_reservations",
        "option_lifecycle_events",
        "option_settlement_materializations",
        "option_settlement_events",
    )
    for table in tables:
        assert f"alter table public.{table} enable row level security" in content
        assert table in content
    assert "from public, anon, authenticated, service_role" in content
    assert "grant select, insert, update on table public.option_positions" in content
    assert " to anon" not in content and " to authenticated" not in content


def test_views_functions_uniqueness_and_immutable_audit_are_declared() -> None:
    content = sql()
    assert content.count("with (security_invoker = true)") >= 2
    for function in (
        "activate_global_cycle_mode",
        "reserve_option_entry",
        "reserve_option_close",
        "record_option_settlement",
        "release_option_collateral",
    ):
        section = content[content.index(f"function public.{function}") :]
        assert "set search_path = ''" in section
    assert "global_orders_one_active_option_close_idx" in content
    assert "global_orders_one_entry_per_cycle_idx" in content
    assert "client_order_id" in content
    assert "assigned_stock_position_id" in content
    assert "insert into public.global_positions" in content
    assert content.count("execute function public.reject_global_audit_mutation()") >= 5


def test_schema_never_persists_secrets_or_invents_market_values() -> None:
    content = sql()
    for forbidden in ("authorization_header", "secret_key", "api_secret", "account_number"):
        assert forbidden not in content
    assert "sanitized_evaluation jsonb not null" in content
    assert "'underlying_price', 1" not in content
    assert "'tradable', true" not in content


def test_pgtap_is_ephemeral_contract_coverage() -> None:
    content = PGTAP.read_text(encoding="utf-8").lower()
    assert "select plan(55)" in content
    assert "rollback" in content
    assert "record_option_settlement" in content
    assert "anon cannot write option positions" in content


def test_reservation_recomputes_all_durable_risk_after_the_lock() -> None:
    content = sql()
    section = content[
        content.index("create function public.reserve_option_entry") : content.index(
            "create function public.reserve_option_close"
        )
    ]
    assert section.index("pg_advisory_xact_lock") < section.index("with stock_risk")
    for required in (
        "public.global_positions",
        "public.companies",
        "public.sectors",
        "public.option_positions",
        "public.collateral_reservations",
        "cycle.mode in ('options', 'mixed')",
        "status in ('reserved', 'consumed')",
        "durable_underlying_exposure",
        "durable_sector_exposure",
        "durable_sector_company_count",
    ):
        assert required in section
    assert "not exists (\n        select 1 from public.collateral_reservations" in section
    assert "p_underlying, p_sector," in section
    assert "p_collateral, 'reserved', p_observed_at" in section


def test_settlement_has_separate_technical_and_economic_identities() -> None:
    content = sql()
    assert "alter table public.global_positions add column sector text" in content
    assert "primary key (activity_id, activity_type)" in content
    assert "create table public.option_settlement_materializations" in content
    assert "economic_event_key text primary key" in content
    assert "option_position_id uuid not null unique" in content
    section = content[
        content.index("create function public.record_option_settlement") : content.index(
            "create view public.public_option_cycle_envelopes"
        )
    ]
    for invariant in (
        "option_position.cycle_id <> p_cycle_id",
        "option_position.occ_symbol <> p_occ_symbol",
        "option_position.underlying_symbol <> p_underlying",
        "p_activity_type not in ('opasn', 'optrd', 'opexp')",
        "p_shares <> 100",
        "p_shares <> 0",
        "option_position.contracts <> 1",
    ):
        assert invariant in section
    assert "public.global_positions.quantity + 100" in section


def test_public_option_view_omits_internal_order_identifiers() -> None:
    content = sql()
    public_view = content[
        content.index("create view public.public_option_cycle_envelopes") : content.index(
            "create view public.internal_option_cycle_envelopes"
        )
    ]
    for forbidden in ("intent_key", "client_order_id", "broker_order_id"):
        assert forbidden not in public_view
    internal_view = content[content.index("create view public.internal_option_cycle_envelopes") :]
    for required in ("intent_key", "client_order_id", "broker_order_id"):
        assert required in internal_view
    assert "grant select on table public.internal_option_cycle_envelopes to service_role" in content
