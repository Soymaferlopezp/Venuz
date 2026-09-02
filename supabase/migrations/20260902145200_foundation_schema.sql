-- Venuz foundation schema. Runtime writes are backend-only and paper-trading only.
create extension if not exists pgcrypto with schema extensions;

alter default privileges for role postgres in schema public
  revoke select, insert, update, delete on tables from anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke usage, select on sequences from anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated, service_role;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 1 and 120),
  timezone text not null default 'America/New_York',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.app_roles (
  user_id uuid primary key references public.profiles(user_id) on delete cascade,
  role text not null default 'operator' check (role in ('operator')),
  created_at timestamptz not null default now()
);

create table public.sectors (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null unique,
  is_prioritized boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.companies (
  id uuid primary key default gen_random_uuid(),
  sector_id uuid not null references public.sectors(id),
  ticker text not null unique check (ticker = upper(ticker)),
  name text not null,
  exchange text not null,
  cik text unique,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.provider_budgets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  provider text not null,
  budget_date date not null,
  request_limit integer not null check (request_limit > 0),
  request_count integer not null default 0 check (request_count between 0 and request_limit),
  updated_at timestamptz not null default now(),
  unique (owner_id, provider, budget_date)
);

create table public.job_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  job_type text not null,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'canceled')),
  progress smallint not null default 0 check (progress between 0 and 100),
  idempotency_key text not null,
  failure_code text,
  failure_detail text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  unique (owner_id, idempotency_key)
);

create table public.financial_facts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  provider text not null,
  taxonomy text not null,
  concept text not null,
  fiscal_year integer not null,
  fiscal_period text not null,
  period_end date not null,
  unit text not null,
  value numeric not null,
  filed_at date,
  source_url text not null,
  source_fetched_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (owner_id, company_id, provider, taxonomy, concept, period_end, fiscal_period)
);

create table public.valuation_snapshots (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  as_of timestamptz not null,
  frozen_until_earnings_at timestamptz,
  current_price numeric(20, 6) not null check (current_price > 0),
  estimated_price_pe numeric(20, 6),
  estimated_price_pfcf numeric(20, 6),
  range_floor numeric(20, 6),
  range_ceiling numeric(20, 6),
  confidence text not null check (confidence in ('high', 'medium', 'low', 'insufficient')),
  status text not null check (status in ('strong_green', 'green', 'yellow', 'red', 'insufficient')),
  observations jsonb not null default '[]'::jsonb,
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.screening_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  job_run_id uuid references public.job_runs(id) on delete set null,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'canceled')),
  strategy_version text not null,
  idempotency_key text not null,
  inputs_hash text not null,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (owner_id, idempotency_key)
);

create table public.screening_results (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  screening_run_id uuid not null references public.screening_runs(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  valuation_snapshot_id uuid references public.valuation_snapshots(id) on delete set null,
  rank integer check (rank > 0),
  eligibility text not null check (eligibility in ('eligible', 'no_trade')),
  overall_status text not null check (overall_status in ('green', 'yellow', 'red', 'insufficient')),
  reasons jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (screening_run_id, company_id)
);

create table public.criterion_results (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  screening_result_id uuid not null references public.screening_results(id) on delete cascade,
  criterion text not null,
  status text not null check (status in ('green', 'yellow', 'red', 'insufficient')),
  formula text not null,
  result jsonb not null,
  reason text not null,
  evidence_as_of timestamptz not null,
  created_at timestamptz not null default now(),
  unique (screening_result_id, criterion)
);

create table public.opportunities (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  screening_result_id uuid not null references public.screening_results(id) on delete cascade,
  status text not null check (status in ('eligible', 'approval_required', 'expired', 'executed', 'rejected')),
  idempotency_key text not null,
  expires_at timestamptz not null,
  guard_results jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (owner_id, idempotency_key)
);

create table public.approval_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  opportunity_id uuid not null references public.opportunities(id) on delete cascade,
  status text not null check (status in ('pending', 'approved', 'rejected', 'expired')),
  reason text not null,
  decision_reason text,
  idempotency_key text not null,
  expires_at timestamptz not null,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (owner_id, idempotency_key)
);

create table public.positions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid not null references public.companies(id),
  broker_position_id text not null,
  quantity numeric(24, 8) not null check (quantity >= 0),
  average_fill_price numeric(20, 6) not null check (average_fill_price > 0),
  status text not null check (status in ('open', 'closing', 'closed')),
  stop_mode text not null check (stop_mode in ('initial', 'fair_price', 'trailing', 'closed')),
  opened_at timestamptz not null,
  closed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (owner_id, broker_position_id)
);

create table public.orders (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  opportunity_id uuid references public.opportunities(id) on delete set null,
  position_id uuid references public.positions(id) on delete set null,
  company_id uuid not null references public.companies(id),
  broker_order_id text unique,
  client_order_id text not null,
  idempotency_key text not null,
  side text not null check (side in ('buy', 'sell')),
  order_type text not null check (order_type in ('market', 'stop', 'trailing_stop')),
  status text not null check (status in ('pending', 'submitted', 'partially_filled', 'filled', 'canceled', 'rejected', 'expired')),
  quantity numeric(24, 8) not null check (quantity > 0),
  submitted_at timestamptz,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (owner_id, client_order_id),
  unique (owner_id, idempotency_key)
);

create table public.order_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  order_id uuid not null references public.orders(id) on delete cascade,
  remote_event_id text,
  event_type text not null,
  broker_status text not null,
  occurred_at timestamptz not null,
  sanitized_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (order_id, remote_event_id)
);

create table public.evidence_items (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  company_id uuid references public.companies(id) on delete cascade,
  screening_result_id uuid references public.screening_results(id) on delete cascade,
  provider text not null,
  evidence_type text not null,
  title text not null,
  source_url text not null,
  published_at timestamptz,
  fetched_at timestamptz not null,
  content_hash text not null,
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (owner_id, provider, content_hash)
);

create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(user_id) on delete cascade,
  actor_id uuid references auth.users(id) on delete set null,
  correlation_id uuid not null,
  event_type text not null,
  entity_type text not null,
  entity_id uuid,
  inputs_hash text not null,
  decision text not null,
  provider_provenance jsonb not null default '{}'::jsonb,
  sanitized_details jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  unique (owner_id, correlation_id, event_type, entity_id)
);

create index companies_sector_id_idx on public.companies (sector_id);
create index provider_budgets_owner_date_idx on public.provider_budgets (owner_id, budget_date desc);
create index job_runs_owner_status_created_idx on public.job_runs (owner_id, status, created_at desc);
create index financial_facts_owner_company_period_idx on public.financial_facts (owner_id, company_id, period_end desc);
create index valuation_snapshots_owner_company_as_of_idx on public.valuation_snapshots (owner_id, company_id, as_of desc);
create index screening_runs_job_run_id_idx on public.screening_runs (job_run_id);
create index screening_runs_owner_created_idx on public.screening_runs (owner_id, created_at desc);
create index screening_results_owner_run_rank_idx on public.screening_results (owner_id, screening_run_id, rank);
create index screening_results_company_id_idx on public.screening_results (company_id);
create index screening_results_valuation_snapshot_id_idx on public.screening_results (valuation_snapshot_id);
create index criterion_results_owner_screening_idx on public.criterion_results (owner_id, screening_result_id);
create index opportunities_owner_status_created_idx on public.opportunities (owner_id, status, created_at desc);
create index opportunities_screening_result_id_idx on public.opportunities (screening_result_id);
create index approval_requests_owner_status_created_idx on public.approval_requests (owner_id, status, created_at desc);
create index approval_requests_opportunity_id_idx on public.approval_requests (opportunity_id);
create index positions_owner_status_idx on public.positions (owner_id, status);
create index positions_company_id_idx on public.positions (company_id);
create index orders_owner_status_created_idx on public.orders (owner_id, status, created_at desc);
create index orders_opportunity_id_idx on public.orders (opportunity_id);
create index orders_position_id_idx on public.orders (position_id);
create index orders_company_id_idx on public.orders (company_id);
create index order_events_owner_order_occurred_idx on public.order_events (owner_id, order_id, occurred_at);
create index evidence_items_owner_company_fetched_idx on public.evidence_items (owner_id, company_id, fetched_at desc);
create index evidence_items_screening_result_id_idx on public.evidence_items (screening_result_id);
create index audit_events_owner_occurred_idx on public.audit_events (owner_id, occurred_at desc);
create index audit_events_actor_id_idx on public.audit_events (actor_id);

create function public.reject_audit_mutation()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  raise exception 'audit_events are append-only';
end;
$$;
create trigger audit_events_immutable before update or delete on public.audit_events
for each row execute function public.reject_audit_mutation();
revoke execute on function public.reject_audit_mutation() from public, anon, authenticated, service_role;

alter table public.profiles enable row level security;
alter table public.app_roles enable row level security;
alter table public.sectors enable row level security;
alter table public.companies enable row level security;
alter table public.provider_budgets enable row level security;
alter table public.job_runs enable row level security;
alter table public.financial_facts enable row level security;
alter table public.valuation_snapshots enable row level security;
alter table public.screening_runs enable row level security;
alter table public.screening_results enable row level security;
alter table public.criterion_results enable row level security;
alter table public.opportunities enable row level security;
alter table public.approval_requests enable row level security;
alter table public.positions enable row level security;
alter table public.orders enable row level security;
alter table public.order_events enable row level security;
alter table public.evidence_items enable row level security;
alter table public.audit_events enable row level security;

revoke all on table public.profiles, public.app_roles, public.sectors, public.companies,
  public.provider_budgets, public.job_runs, public.financial_facts, public.valuation_snapshots,
  public.screening_runs, public.screening_results, public.criterion_results, public.opportunities,
  public.approval_requests, public.positions, public.orders, public.order_events,
  public.evidence_items, public.audit_events from anon, authenticated, service_role;

grant select, insert, update, delete on table public.profiles, public.app_roles, public.sectors,
  public.companies, public.provider_budgets, public.job_runs, public.financial_facts,
  public.valuation_snapshots, public.screening_runs, public.screening_results,
  public.criterion_results, public.opportunities, public.approval_requests, public.positions,
  public.orders, public.order_events, public.evidence_items to service_role;
grant select, insert on table public.audit_events to service_role;
grant select on table public.sectors, public.companies to authenticated;
grant select, update on table public.profiles to authenticated;
grant select on table public.app_roles, public.provider_budgets, public.job_runs,
  public.financial_facts, public.valuation_snapshots, public.screening_runs,
  public.screening_results, public.criterion_results, public.opportunities,
  public.approval_requests, public.positions, public.orders, public.order_events,
  public.evidence_items, public.audit_events to authenticated;

create policy profiles_select_own on public.profiles for select to authenticated
  using ((select auth.uid()) = user_id);
create policy profiles_update_own on public.profiles for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy app_roles_select_own on public.app_roles for select to authenticated
  using ((select auth.uid()) = user_id);
create policy sectors_select_authenticated on public.sectors for select to authenticated using (true);
create policy companies_select_authenticated on public.companies for select to authenticated using (true);
create policy provider_budgets_select_own on public.provider_budgets for select to authenticated using ((select auth.uid()) = owner_id);
create policy job_runs_select_own on public.job_runs for select to authenticated using ((select auth.uid()) = owner_id);
create policy financial_facts_select_own on public.financial_facts for select to authenticated using ((select auth.uid()) = owner_id);
create policy valuation_snapshots_select_own on public.valuation_snapshots for select to authenticated using ((select auth.uid()) = owner_id);
create policy screening_runs_select_own on public.screening_runs for select to authenticated using ((select auth.uid()) = owner_id);
create policy screening_results_select_own on public.screening_results for select to authenticated using ((select auth.uid()) = owner_id);
create policy criterion_results_select_own on public.criterion_results for select to authenticated using ((select auth.uid()) = owner_id);
create policy opportunities_select_own on public.opportunities for select to authenticated using ((select auth.uid()) = owner_id);
create policy approval_requests_select_own on public.approval_requests for select to authenticated using ((select auth.uid()) = owner_id);
create policy positions_select_own on public.positions for select to authenticated using ((select auth.uid()) = owner_id);
create policy orders_select_own on public.orders for select to authenticated using ((select auth.uid()) = owner_id);
create policy order_events_select_own on public.order_events for select to authenticated using ((select auth.uid()) = owner_id);
create policy evidence_items_select_own on public.evidence_items for select to authenticated using ((select auth.uid()) = owner_id);
create policy audit_events_select_own on public.audit_events for select to authenticated using ((select auth.uid()) = owner_id);

comment on table public.audit_events is 'Append-only sanitized decision and lifecycle audit trail.';
comment on column public.orders.client_order_id is 'Idempotent Alpaca Paper client order identifier.';
comment on column public.order_events.sanitized_payload is 'Broker event metadata after secret and sensitive-field redaction.';
