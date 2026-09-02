from pathlib import Path


def test_foundation_schema_has_required_tables_rls_and_policies() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    migration_sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repository_root / "supabase" / "migrations").glob("*.sql"))
    )
    required_tables = {
        "profiles",
        "app_roles",
        "sectors",
        "companies",
        "provider_budgets",
        "job_runs",
        "financial_facts",
        "estimate_snapshots",
        "market_snapshots",
        "ratio_observations",
        "valuation_snapshots",
        "screening_runs",
        "screening_results",
        "criterion_results",
        "watchlists",
        "watchlist_items",
        "opportunities",
        "approval_requests",
        "broker_accounts",
        "positions",
        "orders",
        "order_events",
        "risk_snapshots",
        "evidence_items",
        "audit_events",
    }

    for table in required_tables:
        assert f"create table public.{table}" in migration_sql
        assert f"alter table public.{table} enable row level security;" in migration_sql

    assert "from anon, authenticated, service_role" in migration_sql
    assert "to authenticated" in migration_sql
    assert "reject_audit_mutation" in migration_sql
    assert "audit_events_owner_idempotency_key_key" in migration_sql
