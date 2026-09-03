-- Phase 2 read-only provider cache, atomic quota reservation, and advisor indexes.
create table public.provider_cache_entries (
  id uuid primary key default gen_random_uuid(),
  cache_key text not null unique,
  provider text not null check (provider in ('sec_edgar', 'alpaca', 'alpha_vantage')),
  symbol text,
  period_key text,
  source_as_of timestamptz,
  payload jsonb not null,
  fetched_at timestamptz not null default now(),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  check (expires_at >= fetched_at)
);

create table public.analysis_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  symbol text not null check (symbol = upper(symbol)),
  report_date date,
  generated_at timestamptz not null,
  fresh_until timestamptz not null,
  data_state text not null check (
    data_state in ('fresh', 'stale', 'insufficient', 'provider_exhausted', 'error')
  ),
  thesis jsonb not null,
  created_at timestamptz not null default now(),
  unique (owner_id, symbol, generated_at)
);

create table public.watchlist_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  screening_run_id uuid references public.screening_runs(id) on delete set null,
  generated_at timestamptz not null,
  items jsonb not null,
  created_at timestamptz not null default now()
);

create index provider_cache_entries_lookup_idx
  on public.provider_cache_entries (provider, symbol, period_key, source_as_of desc);
create index provider_cache_entries_expiry_idx on public.provider_cache_entries (expires_at);
create index analysis_snapshots_owner_symbol_generated_idx
  on public.analysis_snapshots (owner_id, symbol, generated_at desc);
create index analysis_snapshots_company_id_idx on public.analysis_snapshots (company_id);
create index watchlist_snapshots_owner_generated_idx
  on public.watchlist_snapshots (owner_id, generated_at desc);
create index watchlist_snapshots_screening_run_id_idx
  on public.watchlist_snapshots (screening_run_id);

create index estimate_snapshots_company_id_idx on public.estimate_snapshots (company_id);
create index evidence_items_company_id_idx on public.evidence_items (company_id);
create index financial_facts_company_id_idx on public.financial_facts (company_id);
create index market_snapshots_company_id_idx on public.market_snapshots (company_id);
create index valuation_snapshots_company_id_idx on public.valuation_snapshots (company_id);
create index watchlists_screening_run_id_idx on public.watchlists (screening_run_id);

alter table public.provider_cache_entries enable row level security;
alter table public.analysis_snapshots enable row level security;
alter table public.watchlist_snapshots enable row level security;
revoke all on table public.provider_cache_entries, public.analysis_snapshots,
  public.watchlist_snapshots from anon, authenticated, service_role;
grant select, insert, update, delete on table public.provider_cache_entries,
  public.analysis_snapshots, public.watchlist_snapshots to service_role;
grant select on table public.analysis_snapshots, public.watchlist_snapshots to authenticated;

create policy analysis_snapshots_select_own on public.analysis_snapshots
  for select to authenticated using ((select auth.uid()) = owner_id);
create policy watchlist_snapshots_select_own on public.watchlist_snapshots
  for select to authenticated using ((select auth.uid()) = owner_id);

create function public.reserve_provider_budget(
  p_owner_id uuid,
  p_provider text,
  p_budget_date date,
  p_request_limit integer
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  remaining integer;
begin
  if p_request_limit < 1 or p_request_limit > 25 then
    raise exception 'provider request limit must be between 1 and 25';
  end if;
  if p_provider <> 'alpha_vantage' then
    raise exception 'unsupported budgeted provider';
  end if;

  insert into public.provider_budgets (
    owner_id, provider, budget_date, request_limit, request_count
  )
  values (p_owner_id, p_provider, p_budget_date, p_request_limit, 1)
  on conflict (owner_id, provider, budget_date) do update
    set request_count = public.provider_budgets.request_count + 1,
        request_limit = least(public.provider_budgets.request_limit, excluded.request_limit),
        updated_at = now()
    where public.provider_budgets.request_count < public.provider_budgets.request_limit
  returning request_limit - request_count into remaining;

  if remaining is null then
    raise sqlstate 'PGRST' using
      message = json_build_object(
        'code', 'provider_exhausted',
        'message', 'Provider daily budget exhausted'
      )::text,
      detail = json_build_object('status', 409)::text;
  end if;
  return remaining;
end;
$$;

revoke execute on function public.reserve_provider_budget(uuid, text, date, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_provider_budget(uuid, text, date, integer)
  to service_role;

comment on table public.provider_cache_entries is
  'Backend-only sanitized cache. Authorization headers and provider secrets are forbidden.';
comment on table public.analysis_snapshots is
  'Canonical immutable analysis envelope used to reproduce a thesis and its quarterly freeze.';
comment on table public.watchlist_snapshots is
  'Canonical immutable watchlist envelope; normalized screening rows remain the audit index.';
