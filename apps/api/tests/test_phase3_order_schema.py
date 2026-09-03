import re
from pathlib import Path

MIGRATION = (
    Path(__file__).parents[3] / "supabase/migrations/20260903043000_phase3_global_cycles.sql"
)
PGTAP = Path(__file__).parents[3] / "supabase/tests/phase3_cycles_rls.test.sql"
MIGRATION_DIR = MIGRATION.parent


def test_unapplied_phase3_migration_contains_durable_order_lifecycle() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "global_positions",
        "global_orders",
        "global_order_events",
        "global_approval_requests",
        "global_audit_events",
    ):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "create function public.reserve_global_order" in sql
    assert "security invoker" in sql
    assert "global_orders_one_active_close_idx" in sql
    assert "capture_global_order_event_trigger" in sql
    assert "global_order_events_immutable" in sql
    assert "global_audit_events_immutable" in sql
    assert "entry_filled_quantity" in sql and "exit_filled_quantity" in sql
    assert "alter table public.orders add column client_order_id" not in sql
    assert "protection_mode = 'exiting'" in sql
    assert "fundamentals.critical_exit_reserved" in sql
    assert "on conflict (intent_key) do nothing" in sql


def test_phase3_objects_do_not_collide_with_prior_migrations() -> None:
    current = MIGRATION.read_text(encoding="utf-8").lower()
    prior = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(MIGRATION_DIR.glob("*.sql"))
        if path.name < MIGRATION.name
    )
    object_pattern = re.compile(
        r"create (?:table|view|function|(?:unique )?index|trigger) (?:public\.)?([a-z0-9_]+)"
    )
    current_objects = set(object_pattern.findall(current))
    prior_objects = set(object_pattern.findall(prior))
    assert current_objects.isdisjoint(prior_objects)
    assert "alter table public.orders add" not in current


def test_phase3_functions_and_public_access_are_hardened() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "security definer" not in sql
    assert sql.count("create function public.") == sql.count("security invoker")
    assert sql.count("create function public.") == sql.count("set search_path")
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant select, insert on table public.global_order_events" in sql
    assert "public.global_order_events, public.global_audit_events to service_role" in sql
    assert "grant delete" not in sql


def test_phase3_pgtap_contract_covers_rls_privileges_and_immutability() -> None:
    sql = PGTAP.read_text(encoding="utf-8").lower()
    assert "select plan(35)" in sql
    assert "anon cannot query orders" in sql
    assert "authenticated cannot query orders" in sql
    assert "backend can reserve orders" in sql
    assert "order intent is unique" in sql
    assert "order events are immutable" in sql
    assert "audit events are immutable" in sql
