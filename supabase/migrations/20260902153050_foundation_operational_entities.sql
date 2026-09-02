-- Completes the Phase 1 persistence contracts named in docs/ARCHITECTURE.md.
create table public.estimate_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  provider text not null check (provider = 'alpha_vantage'),
  comparable_period text not null,
  consensus_eps numeric(20, 6),
  previous_consensus_eps numeric(20, 6),
  prior_year_eps numeric(20, 6),
  consensus_revenue numeric,
  source_as_of timestamptz not null,
  fetched_at timestamptz not null,
  provenance jsonb not null default '{}'::jsonb,
  unique (owner_id, company_id, provider, comparable_period, source_as_of)
);

create table public.market_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  provider text not null check (provider = 'alpaca'),
  price numeric(20, 6) not null check (price > 0),
  bid_price numeric(20, 6) check (bid_price > 0),
  ask_price numeric(20, 6) check (ask_price > 0),
  average_daily_dollar_volume numeric check (average_daily_dollar_volume >= 0),
  observed_at timestamptz not null,
  fetched_at timestamptz not null,
  provenance jsonb not null default '{}'::jsonb,
  unique (owner_id, company_id, provider, observed_at)
);

create table public.ratio_observations (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  valuation_snapshot_id uuid not null references public.valuation_snapshots(id) on delete cascade,
  ratio_type text not null check (ratio_type in ('pe', 'pfcf')),
  period_end date not null,
  value numeric(20, 6),
  included boolean not null,
  exclusion_reason text,
  source_url text not null,
  created_at timestamptz not null default now(),
  check (included or exclusion_reason is not null),
  unique (valuation_snapshot_id, ratio_type, period_end)
);

create table public.watchlists (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  screening_run_id uuid not null references public.screening_runs(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (owner_id, screening_run_id)
);

create table public.watchlist_items (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  watchlist_id uuid not null references public.watchlists(id) on delete cascade,
  screening_result_id uuid not null references public.screening_results(id) on delete cascade,
  rank integer not null check (rank between 1 and 15),
  created_at timestamptz not null default now(),
  unique (watchlist_id, screening_result_id),
  unique (watchlist_id, rank)
);

create table public.broker_accounts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  provider text not null check (provider = 'alpaca'),
  trading_mode text not null check (trading_mode = 'paper'),
  broker_account_ref_hash text not null,
  status text not null,
  last_reconciled_at timestamptz,
  sanitized_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, provider),
  unique (provider, broker_account_ref_hash)
);

create table public.risk_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  position_id uuid references public.positions(id) on delete cascade,
  opportunity_id uuid references public.opportunities(id) on delete cascade,
  portfolio_equity numeric(20, 6) not null check (portfolio_equity >= 0),
  cash_after_trade numeric(20, 6) not null check (cash_after_trade >= 0),
  position_pct numeric(8, 6) not null check (position_pct between 0 and 0.10),
  sector_pct numeric(8, 6) not null check (sector_pct between 0 and 0.20),
  cash_pct numeric(8, 6) not null check (cash_pct between 0.20 and 1),
  guard_results jsonb not null default '[]'::jsonb,
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  check (position_id is not null or opportunity_id is not null)
);

alter table public.audit_events add column idempotency_key text not null;
alter table public.audit_events
  add constraint audit_events_owner_idempotency_key_key unique (owner_id, idempotency_key);

create index estimate_snapshots_owner_company_as_of_idx on public.estimate_snapshots (owner_id, company_id, source_as_of desc);
create index market_snapshots_owner_company_observed_idx on public.market_snapshots (owner_id, company_id, observed_at desc);
create index ratio_observations_owner_valuation_idx on public.ratio_observations (owner_id, valuation_snapshot_id, ratio_type);
create index watchlists_owner_created_idx on public.watchlists (owner_id, created_at desc);
create index watchlist_items_owner_watchlist_rank_idx on public.watchlist_items (owner_id, watchlist_id, rank);
create index watchlist_items_screening_result_id_idx on public.watchlist_items (screening_result_id);
create index broker_accounts_owner_id_idx on public.broker_accounts (owner_id);
create index risk_snapshots_owner_observed_idx on public.risk_snapshots (owner_id, observed_at desc);
create index risk_snapshots_position_id_idx on public.risk_snapshots (position_id);
create index risk_snapshots_opportunity_id_idx on public.risk_snapshots (opportunity_id);

alter table public.estimate_snapshots enable row level security;
alter table public.market_snapshots enable row level security;
alter table public.ratio_observations enable row level security;
alter table public.watchlists enable row level security;
alter table public.watchlist_items enable row level security;
alter table public.broker_accounts enable row level security;
alter table public.risk_snapshots enable row level security;

revoke all on table public.estimate_snapshots, public.market_snapshots,
  public.ratio_observations, public.watchlists, public.watchlist_items,
  public.broker_accounts, public.risk_snapshots from anon, authenticated, service_role;
grant select, insert, update, delete on table public.estimate_snapshots,
  public.market_snapshots, public.ratio_observations, public.watchlists,
  public.watchlist_items, public.broker_accounts, public.risk_snapshots to service_role;
grant select on table public.estimate_snapshots, public.market_snapshots,
  public.ratio_observations, public.watchlists, public.watchlist_items,
  public.broker_accounts, public.risk_snapshots to authenticated;

create policy estimate_snapshots_select_own on public.estimate_snapshots for select to authenticated using ((select auth.uid()) = owner_id);
create policy market_snapshots_select_own on public.market_snapshots for select to authenticated using ((select auth.uid()) = owner_id);
create policy ratio_observations_select_own on public.ratio_observations for select to authenticated using ((select auth.uid()) = owner_id);
create policy watchlists_select_own on public.watchlists for select to authenticated using ((select auth.uid()) = owner_id);
create policy watchlist_items_select_own on public.watchlist_items for select to authenticated using ((select auth.uid()) = owner_id);
create policy broker_accounts_select_own on public.broker_accounts for select to authenticated using ((select auth.uid()) = owner_id);
create policy risk_snapshots_select_own on public.risk_snapshots for select to authenticated using ((select auth.uid()) = owner_id);

comment on column public.broker_accounts.broker_account_ref_hash is 'One-way reference only; raw account identifiers are not stored.';
comment on column public.broker_accounts.sanitized_metadata is 'Non-sensitive paper-account metadata only.';
