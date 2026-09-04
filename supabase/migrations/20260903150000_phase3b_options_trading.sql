-- Phase 3B: deterministic, Paper-only Cash-Secured Put lifecycle.
alter table public.global_cycles
  add column mode text not null default 'stocks'
    check (mode in ('stocks', 'options', 'mixed')),
  add column selected_asset_class text
    check (selected_asset_class in ('stock', 'option')),
  add column options_capability_status text not null default 'not_required'
    check (options_capability_status in ('not_required', 'available', 'blocked', 'unavailable'));

create index global_cycles_mode_updated_idx
  on public.global_cycles (mode, updated_at desc);

create or replace view public.public_cycle_envelopes
with (security_invoker = true) as
select c.id as cycle_id, c.cycle_key, c.state, c.data_freshness, c.paper_order_submitted,
 c.blocked_reasons, c.evidence_links, c.provider_provenance, c.updated_at,
 coalesce(jsonb_agg(jsonb_build_object('state',e.state,'occurred_at',e.occurred_at,'message',e.message)
 order by e.occurred_at) filter (where e.id is not null),'[]'::jsonb) as events,
 c.mode, c.selected_asset_class, c.options_capability_status
from public.global_cycles c
left join public.global_cycle_events e on e.cycle_id = c.id
group by c.id;
revoke all on table public.public_cycle_envelopes from public, anon, authenticated, service_role;
grant select on table public.public_cycle_envelopes to service_role;

create function public.activate_global_cycle_mode(
  p_cycle_key text,
  p_mode text,
  p_now timestamptz,
  p_options_capability_status text,
  p_blocked_reasons jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  c public.global_cycles;
  parts text[];
begin
  parts := string_to_array(p_cycle_key, ':');
  if p_mode not in ('stocks', 'options', 'mixed')
     or array_length(parts, 1) < 6
     or parts[2] <> p_mode
     or length(p_cycle_key) > 256 then
    raise exception 'invalid mode-aware cycle key';
  end if;
  if p_mode = 'stocks' and p_options_capability_status <> 'not_required' then
    raise exception 'stocks capability status must be not_required';
  end if;
  insert into public.global_cycles(
    cycle_key, strategy_version, market_session, data_cutoff, mode,
    options_capability_status, blocked_reasons, state, updated_at
  ) values (
    p_cycle_key, parts[1], parts[3]::date,
    array_to_string(parts[4:array_length(parts, 1)], ':')::timestamptz,
    p_mode, p_options_capability_status, coalesce(p_blocked_reasons, '[]'::jsonb),
    case when p_mode <> 'stocks' and p_options_capability_status <> 'available'
      then 'blocked' else 'queued' end, p_now
  ) on conflict(cycle_key) do update set cycle_key = excluded.cycle_key
  returning * into c;
  insert into public.global_cycle_events(cycle_id, state, message, occurred_at)
  values(c.id, c.state,
    case when c.state = 'blocked' then 'Options capability blocked' else 'Cycle queued' end,
    p_now) on conflict do nothing;
  return (select to_jsonb(v) from public.public_cycle_envelopes v where v.cycle_id = c.id);
end;
$$;
revoke execute on function public.activate_global_cycle_mode(text,text,timestamptz,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.activate_global_cycle_mode(text,text,timestamptz,text,jsonb)
  to service_role;

create table public.options_capability_checks (
  id uuid primary key default gen_random_uuid(),
  status text not null check (status in ('available', 'blocked', 'unavailable')),
  options_approved_level smallint check (options_approved_level between 0 and 3),
  options_trading_level smallint check (options_trading_level between 0 and 3),
  buying_power_available boolean not null,
  paper_endpoint_valid boolean not null,
  option_assets_available boolean not null,
  contracts_accessible boolean not null,
  chains_accessible boolean not null,
  snapshots_accessible boolean not null,
  feed text check (feed in ('opra', 'indicative')),
  blocking_reasons jsonb not null default '[]'::jsonb,
  checked_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table public.option_contract_observations (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  occ_symbol text not null check (length(occ_symbol) between 15 and 32),
  underlying_symbol text not null check (underlying_symbol = upper(underlying_symbol)),
  underlying_kind text not null check (underlying_kind in ('equity', 'etf')),
  sector text not null,
  contract_type text not null check (contract_type = 'put'),
  expiration date not null,
  strike numeric(20,8) not null check (strike > 0),
  dte smallint not null check (dte between 0 and 3660),
  delta numeric(10,8),
  bid numeric(20,8),
  ask numeric(20,8),
  spread_absolute numeric(20,8),
  spread_pct numeric(20,10),
  volume bigint check (volume >= 0),
  open_interest bigint check (open_interest >= 0),
  implied_volatility numeric(20,10),
  realized_volatility numeric(20,10),
  realized_volatility_window smallint check (realized_volatility_window between 10 and 252),
  iv_relative_ratio numeric(20,10),
  feed text check (feed in ('opra', 'indicative')),
  quote_at timestamptz,
  provider text not null check (provider = 'alpaca'),
  freshness text not null check (freshness in ('fresh', 'stale', 'unavailable')),
  sanitized_provenance jsonb not null default '{}'::jsonb,
  observed_at timestamptz not null,
  unique (cycle_id, occ_symbol, observed_at)
);

create table public.option_candidate_evaluations (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  observation_id uuid not null references public.option_contract_observations(id) on delete restrict,
  occ_symbol text not null,
  strategy_version text not null,
  eligible boolean not null,
  selected boolean not null default false,
  rank_score numeric(20,10),
  collateral numeric(20,2) not null check (collateral > 0),
  guard_results jsonb not null,
  rejected_reasons jsonb not null default '[]'::jsonb,
  sanitized_evaluation jsonb not null,
  evaluated_at timestamptz not null,
  unique (cycle_id, occ_symbol)
);
create unique index option_candidate_one_selected_per_cycle_idx
  on public.option_candidate_evaluations (cycle_id) where selected;

create table public.option_positions (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  occ_symbol text not null,
  underlying_symbol text not null check (underlying_symbol = upper(underlying_symbol)),
  sector text not null,
  contracts smallint not null check (contracts between 0 and 1),
  strike numeric(20,8) not null check (strike > 0),
  expiration date not null,
  entry_credit_per_share numeric(20,8) not null check (entry_credit_per_share > 0),
  entry_credit_total numeric(20,2) not null check (entry_credit_total > 0),
  collateral numeric(20,2) not null check (collateral = strike * 100),
  status text not null check (status in ('open', 'closing', 'assigned', 'expired', 'closed')),
  exit_reason text not null default 'none'
    check (exit_reason in ('none','critical_risk','stop_loss','dte_21','take_profit')),
  opened_at timestamptz not null,
  updated_at timestamptz not null,
  closed_at timestamptz,
  unique (cycle_id, occ_symbol)
);
create unique index option_positions_one_open_contract_idx
  on public.option_positions (occ_symbol) where status in ('open', 'closing');
create index option_positions_status_expiration_idx
  on public.option_positions (status, expiration);

create table public.collateral_reservations (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  option_position_id uuid references public.option_positions(id) on delete restrict,
  intent_key text not null unique,
  occ_symbol text not null,
  underlying_symbol text not null check (underlying_symbol = upper(underlying_symbol)),
  sector text not null,
  amount numeric(20,2) not null check (amount > 0),
  status text not null check (status in ('reserved', 'consumed', 'released')),
  reserved_at timestamptz not null,
  released_at timestamptz,
  check ((status = 'released') = (released_at is not null))
);
create index collateral_reservations_status_idx
  on public.collateral_reservations (status, reserved_at);
create index collateral_reservations_risk_idx
  on public.collateral_reservations (underlying_symbol, sector, status)
  where status in ('reserved', 'consumed');

create table public.option_lifecycle_events (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  option_position_id uuid references public.option_positions(id) on delete restrict,
  event_type text not null,
  state text not null,
  reason text not null,
  sanitized_details jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null
);
create index option_lifecycle_events_cycle_time_idx
  on public.option_lifecycle_events (cycle_id, occurred_at);

create table public.option_settlement_materializations (
  economic_event_key text primary key,
  option_position_id uuid not null unique references public.option_positions(id) on delete restrict,
  event_kind text not null check (event_kind in ('assignment', 'expiration')),
  assigned_stock_position_id uuid references public.global_positions(id) on delete restrict,
  materialized_at timestamptz not null,
  check ((event_kind = 'assignment') = (assigned_stock_position_id is not null))
);

create table public.option_settlement_events (
  activity_id text not null,
  activity_type text not null check (activity_type in ('OPASN', 'OPTRD', 'OPEXP')),
  economic_event_key text not null references public.option_settlement_materializations(economic_event_key),
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  option_position_id uuid not null references public.option_positions(id) on delete restrict,
  assigned_stock_position_id uuid references public.global_positions(id) on delete restrict,
  occ_symbol text not null,
  underlying text not null,
  shares smallint not null check (shares in (0, 100)),
  cash_effect numeric(20,8),
  occurred_at timestamptz not null,
  processed_at timestamptz not null default now(),
  primary key (activity_id, activity_type),
  check ((activity_type in ('OPASN', 'OPTRD') and shares = 100)
      or (activity_type = 'OPEXP' and shares = 0))
);
create index option_settlement_events_cycle_time_idx
  on public.option_settlement_events (cycle_id, occurred_at);
create index option_settlement_events_economic_idx
  on public.option_settlement_events (economic_event_key, occurred_at);

alter table public.global_orders drop constraint global_orders_symbol_check;
alter table public.global_orders
  add constraint global_orders_symbol_check
    check (symbol = upper(symbol) and length(symbol) between 1 and 32);
alter table public.global_orders drop constraint global_orders_purpose_check;
alter table public.global_orders
  add constraint global_orders_purpose_check check (
    purpose in ('entry','initial_stop','estimated_price_stop','trailing_stop','critical_exit',
                'option_entry','option_close')
  ),
  add column asset_class text not null default 'stock'
    check (asset_class in ('stock', 'option')),
  add column position_intent text
    check (position_intent in ('sell_to_open', 'buy_to_close')),
  add column underlying_symbol text,
  add column option_position_id uuid references public.option_positions(id) on delete restrict,
  add constraint global_orders_option_shape_check check (
    (asset_class = 'stock' and position_intent is null and option_position_id is null)
    or
    (asset_class = 'option' and order_type = 'market' and quantity = 1
      and position_intent is not null and underlying_symbol is not null)
  );
create unique index global_orders_one_entry_per_cycle_idx
  on public.global_orders (cycle_id) where purpose in ('entry', 'option_entry');
create unique index global_orders_one_active_option_close_idx
  on public.global_orders (option_position_id)
  where position_intent = 'buy_to_close'
    and status in ('pending','submitted','partially_filled');
create index global_orders_asset_reconciliation_idx
  on public.global_orders (asset_class, status, observed_at);

alter table public.global_positions add column sector text;
create index global_positions_sector_risk_idx
  on public.global_positions (sector, symbol) where quantity > 0;

alter table public.options_capability_checks enable row level security;
alter table public.option_contract_observations enable row level security;
alter table public.option_candidate_evaluations enable row level security;
alter table public.option_positions enable row level security;
alter table public.collateral_reservations enable row level security;
alter table public.option_lifecycle_events enable row level security;
alter table public.option_settlement_materializations enable row level security;
alter table public.option_settlement_events enable row level security;

revoke all on table public.options_capability_checks, public.option_contract_observations,
  public.option_candidate_evaluations, public.option_positions, public.collateral_reservations,
  public.option_lifecycle_events, public.option_settlement_materializations,
  public.option_settlement_events from public, anon, authenticated, service_role;
grant select, insert on table public.options_capability_checks,
  public.option_contract_observations, public.option_candidate_evaluations,
  public.option_lifecycle_events, public.option_settlement_materializations,
  public.option_settlement_events to service_role;
grant select, insert, update on table public.option_positions,
  public.collateral_reservations to service_role;

create trigger option_contract_observations_immutable
before update or delete on public.option_contract_observations
for each row execute function public.reject_global_audit_mutation();
create trigger option_candidate_evaluations_immutable
before update or delete on public.option_candidate_evaluations
for each row execute function public.reject_global_audit_mutation();
create trigger option_lifecycle_events_immutable
before update or delete on public.option_lifecycle_events
for each row execute function public.reject_global_audit_mutation();
create trigger option_settlement_materializations_immutable
before update or delete on public.option_settlement_materializations
for each row execute function public.reject_global_audit_mutation();
create trigger option_settlement_events_immutable
before update or delete on public.option_settlement_events
for each row execute function public.reject_global_audit_mutation();

create function public.consume_option_collateral()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.contracts = 1 and new.status in ('open', 'closing') then
    update public.collateral_reservations
    set option_position_id = new.id, status = 'consumed'
    where cycle_id = new.cycle_id and occ_symbol = new.occ_symbol and status = 'reserved';
  end if;
  return new;
end;
$$;
create trigger option_positions_consume_collateral
after insert or update of contracts, status on public.option_positions
for each row execute function public.consume_option_collateral();

create function public.reserve_option_entry(
  p_order_id uuid, p_cycle_id uuid, p_intent_key text, p_client_order_id text,
  p_occ_symbol text, p_underlying text, p_sector text, p_expiration date,
  p_strike numeric, p_collateral numeric, p_cash numeric, p_equity numeric,
  p_options_buying_power numeric, p_current_position_exposure numeric,
  p_current_sector_exposure numeric, p_sector_company_count integer,
  p_evaluation jsonb, p_observed_at timestamptz
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  o public.global_orders;
  active_option_collateral numeric := 0;
  durable_underlying_exposure numeric := 0;
  durable_sector_exposure numeric := 0;
  durable_sector_company_count integer := 0;
  underlying_already_exposed boolean := false;
  observation_id uuid := gen_random_uuid();
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('venuz-options-account'));

  select * into o from public.global_orders where intent_key = p_intent_key;
  if o.id is not null then
    if o.cycle_id <> p_cycle_id or o.symbol <> p_occ_symbol
       or o.client_order_id <> p_client_order_id or o.position_intent <> 'sell_to_open' then
      raise exception 'option intent identity mismatch';
    end if;
    return to_jsonb(o) || jsonb_build_object('reservation_created', false);
  end if;

  if not exists (
    select 1 from public.global_cycles
    where id = p_cycle_id and mode in ('options', 'mixed')
  ) then
    raise exception 'option reservation requires an options or mixed cycle';
  end if;
  if coalesce((p_evaluation->>'eligible')::boolean, false) is not true then
    raise exception 'option evaluation is not eligible';
  end if;
  if p_collateral <> p_strike * 100 or p_equity <= 0
     or p_cash < 0 or p_options_buying_power < p_collateral then
    raise exception 'option collateral snapshot is invalid';
  end if;

  with stock_risk as (
    select gp.symbol as underlying_symbol,
      lower(coalesce(gp.sector, s.name, s.slug, 'unknown')) as sector_key,
      gp.quantity * gp.average_fill_price as amount,
      'stock'::text as risk_kind
    from public.global_positions gp
    left join public.companies company on company.ticker = gp.symbol
    left join public.sectors s on s.id = company.sector_id
    where gp.quantity > 0
  ), reservation_risk as (
    select cr.underlying_symbol, lower(cr.sector) as sector_key, cr.amount,
      'option'::text as risk_kind
    from public.collateral_reservations cr
    join public.global_cycles cycle on cycle.id = cr.cycle_id
    where cr.status in ('reserved', 'consumed') and cycle.mode in ('options', 'mixed')
  ), orphan_option_risk as (
    select position.underlying_symbol, lower(position.sector) as sector_key,
      position.collateral as amount, 'option'::text as risk_kind
    from public.option_positions position
    join public.global_cycles cycle on cycle.id = position.cycle_id
    where position.status in ('open', 'closing') and position.contracts = 1
      and cycle.mode in ('options', 'mixed')
      and not exists (
        select 1 from public.collateral_reservations cr
        where cr.option_position_id = position.id and cr.status in ('reserved', 'consumed')
      )
  ), durable_risk as (
    select * from stock_risk
    union all select * from reservation_risk
    union all select * from orphan_option_risk
  )
  select
    coalesce(sum(amount) filter (where risk_kind = 'option'), 0),
    coalesce(sum(amount) filter (where underlying_symbol = p_underlying), 0),
    coalesce(sum(amount) filter (where sector_key = lower(p_sector)), 0),
    count(distinct underlying_symbol) filter (where sector_key = lower(p_sector)),
    coalesce(bool_or(underlying_symbol = p_underlying), false)
  into active_option_collateral, durable_underlying_exposure,
    durable_sector_exposure, durable_sector_company_count, underlying_already_exposed
  from durable_risk;

  if (p_cash - active_option_collateral - p_collateral) / p_equity < 0.20
     or (durable_underlying_exposure + p_collateral) / p_equity > 0.10
     or (durable_sector_exposure + p_collateral) / p_equity > 0.20
     or (durable_sector_company_count >= 2 and not underlying_already_exposed) then
    raise exception 'durable option cash or global exposure guard failed';
  end if;

  insert into public.option_contract_observations(
    id, cycle_id, occ_symbol, underlying_symbol, underlying_kind, sector, contract_type,
    expiration, strike, dte, delta, bid, ask, spread_absolute, spread_pct, volume,
    open_interest, implied_volatility, realized_volatility, realized_volatility_window,
    iv_relative_ratio, feed, quote_at, provider, freshness, sanitized_provenance, observed_at
  ) values (
    observation_id, p_cycle_id, p_occ_symbol, p_underlying,
    p_evaluation->'candidate'->>'underlying_kind', p_sector, 'put', p_expiration, p_strike,
    (p_expiration - p_observed_at::date)::smallint,
    (p_evaluation->'candidate'->>'delta')::numeric,
    (p_evaluation->'candidate'->>'bid')::numeric,
    (p_evaluation->'candidate'->>'ask')::numeric,
    (p_evaluation->>'spread_absolute')::numeric,
    (p_evaluation->>'spread_pct')::numeric,
    (p_evaluation->'candidate'->>'volume')::bigint,
    (p_evaluation->'candidate'->>'open_interest')::bigint,
    (p_evaluation->'candidate'->>'implied_volatility')::numeric,
    (p_evaluation->'candidate'->>'realized_volatility')::numeric,
    (p_evaluation->'candidate'->>'realized_volatility_window')::smallint,
    (p_evaluation->>'iv_relative_ratio')::numeric,
    p_evaluation->'candidate'->>'feed',
    (p_evaluation->'candidate'->>'quote_at')::timestamptz,
    'alpaca', 'fresh', jsonb_build_object('provider', 'alpaca'), p_observed_at
  );
  insert into public.option_candidate_evaluations(
    id, cycle_id, observation_id, occ_symbol, strategy_version, eligible, selected,
    rank_score, collateral, guard_results, rejected_reasons, sanitized_evaluation, evaluated_at
  ) values (
    p_order_id, p_cycle_id, observation_id, p_occ_symbol, p_evaluation->>'strategy_version',
    true, true, (p_evaluation->>'score')::numeric, p_collateral,
    p_evaluation->'guards', p_evaluation->'rejected_reasons', p_evaluation, p_observed_at
  );
  insert into public.collateral_reservations(
    id, cycle_id, intent_key, occ_symbol, underlying_symbol, sector, amount, status, reserved_at
  ) values (
    gen_random_uuid(), p_cycle_id, p_intent_key, p_occ_symbol, p_underlying, p_sector,
    p_collateral, 'reserved', p_observed_at
  );
  insert into public.global_orders(
    id, cycle_id, intent_key, client_order_id, symbol, purpose, side, order_type,
    status, quantity, observed_at, asset_class, position_intent, underlying_symbol
  ) values (
    p_order_id, p_cycle_id, p_intent_key, p_client_order_id, p_occ_symbol,
    'option_entry', 'sell', 'market', 'pending', 1, p_observed_at,
    'option', 'sell_to_open', p_underlying
  ) returning * into o;
  return to_jsonb(o) || jsonb_build_object('reservation_created', true);
end;
$$;

create function public.reserve_option_close(
  p_order_id uuid, p_position_id uuid, p_intent_key text,
  p_client_order_id text, p_reason text, p_observed_at timestamptz
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  p public.option_positions;
  o public.global_orders;
  was_created boolean := true;
begin
  select * into strict p from public.option_positions
  where id = p_position_id for update;
  if p.contracts <> 1 or p.status not in ('open', 'closing') then
    raise exception 'option position is not closable';
  end if;
  insert into public.global_orders(
    id, cycle_id, option_position_id, intent_key, client_order_id, symbol,
    purpose, side, order_type, status, quantity, observed_at, asset_class,
    position_intent, underlying_symbol
  ) values (
    p_order_id, p.cycle_id, p.id, p_intent_key, p_client_order_id, p.occ_symbol,
    'option_close', 'buy', 'market', 'pending', 1, p_observed_at, 'option',
    'buy_to_close', p.underlying_symbol
  ) on conflict (intent_key) do nothing returning * into o;
  if o.id is null then
    was_created := false;
    select * into strict o from public.global_orders where intent_key = p_intent_key;
  else
    update public.option_positions set status = 'closing', exit_reason = p_reason,
      updated_at = p_observed_at where id = p.id;
    insert into public.option_lifecycle_events(
      id, cycle_id, option_position_id, event_type, state, reason,
      sanitized_details, occurred_at
    ) values (
      p_order_id, p.cycle_id, p.id, 'option.close_reserved', 'closing', p_reason,
      jsonb_build_object('position_intent', 'buy_to_close'), p_observed_at
    );
  end if;
  return to_jsonb(o) || jsonb_build_object('reservation_created', was_created);
end;
$$;

revoke execute on function public.reserve_option_entry(
  uuid,uuid,text,text,text,text,text,date,numeric,numeric,numeric,numeric,numeric,
  numeric,numeric,integer,jsonb,timestamptz
) from public, anon, authenticated;
grant execute on function public.reserve_option_entry(
  uuid,uuid,text,text,text,text,text,date,numeric,numeric,numeric,numeric,numeric,
  numeric,numeric,integer,jsonb,timestamptz
) to service_role;
revoke execute on function public.reserve_option_close(uuid,uuid,text,text,text,timestamptz)
  from public, anon, authenticated;
grant execute on function public.reserve_option_close(uuid,uuid,text,text,text,timestamptz)
  to service_role;

create function public.release_option_collateral(p_intent_key text, p_now timestamptz)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
begin
  update public.collateral_reservations
  set status = 'released', released_at = p_now
  where intent_key = p_intent_key and status <> 'released';
  return found;
end;
$$;
revoke execute on function public.release_option_collateral(text,timestamptz)
  from public, anon, authenticated;
grant execute on function public.release_option_collateral(text,timestamptz) to service_role;

create function public.record_option_settlement(
  p_activity_id text, p_cycle_id uuid, p_position_id uuid, p_activity_type text,
  p_occ_symbol text, p_underlying text, p_shares integer, p_cash_effect numeric,
  p_occurred_at timestamptz
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  option_position public.option_positions;
  existing_event public.option_settlement_events;
  materialization public.option_settlement_materializations;
  economic_key text;
  event_kind text;
  stock_position_id uuid;
  newly_materialized boolean := false;
begin
  select * into strict option_position from public.option_positions
  where id = p_position_id for update;

  if p_activity_id is null or length(p_activity_id) = 0
     or option_position.cycle_id <> p_cycle_id
     or option_position.occ_symbol <> p_occ_symbol
     or option_position.underlying_symbol <> p_underlying
     or p_activity_type not in ('OPASN', 'OPTRD', 'OPEXP')
     or (p_activity_type in ('OPASN', 'OPTRD') and p_shares <> 100)
     or (p_activity_type = 'OPEXP' and p_shares <> 0) then
    raise exception 'option settlement invariant mismatch';
  end if;

  select * into existing_event from public.option_settlement_events
  where activity_id = p_activity_id and activity_type = p_activity_type;
  if existing_event.activity_id is not null then
    if existing_event.cycle_id <> p_cycle_id
       or existing_event.option_position_id <> p_position_id
       or existing_event.occ_symbol <> p_occ_symbol
       or existing_event.underlying <> p_underlying
       or existing_event.shares <> p_shares
       or existing_event.cash_effect is distinct from p_cash_effect
       or existing_event.occurred_at <> p_occurred_at then
      raise exception 'option settlement technical identity mismatch';
    end if;
    return false;
  end if;

  event_kind := case when p_activity_type = 'OPEXP' then 'expiration' else 'assignment' end;
  economic_key := p_position_id::text || ':' || event_kind;
  select * into materialization from public.option_settlement_materializations
  where option_position_id = p_position_id for update;

  if materialization.economic_event_key is not null then
    if materialization.event_kind <> event_kind
       or materialization.economic_event_key <> economic_key
       or option_position.contracts <> 0
       or (event_kind = 'assignment' and option_position.status <> 'assigned')
       or (event_kind = 'expiration' and option_position.status <> 'expired') then
      raise exception 'option settlement economic identity mismatch';
    end if;
    stock_position_id := materialization.assigned_stock_position_id;
  else
    if option_position.contracts <> 1 or option_position.status not in ('open', 'closing') then
      raise exception 'option settlement requires one open contract';
    end if;

    if event_kind = 'assignment' then
      insert into public.global_positions(
        id, cycle_id, symbol, quantity, entry_filled_quantity, average_fill_price,
        protection_mode, sector, created_at, updated_at
      ) values (
        gen_random_uuid(), p_cycle_id, p_underlying, 100, 100, option_position.strike,
        'initial', option_position.sector, p_occurred_at, p_occurred_at
      ) on conflict (cycle_id, symbol) do update set
        average_fill_price = (
          public.global_positions.average_fill_price * public.global_positions.quantity
          + excluded.average_fill_price * 100
        ) / (public.global_positions.quantity + 100),
        quantity = public.global_positions.quantity + 100,
        entry_filled_quantity = public.global_positions.entry_filled_quantity + 100,
        sector = coalesce(public.global_positions.sector, excluded.sector),
        updated_at = excluded.updated_at
      returning id into stock_position_id;
    end if;

    update public.option_positions
    set contracts = 0,
      status = case when event_kind = 'assignment' then 'assigned' else 'expired' end,
      closed_at = p_occurred_at, updated_at = p_occurred_at
    where id = p_position_id;
    update public.collateral_reservations
    set status = 'released', released_at = p_occurred_at
    where status <> 'released'
      and (option_position_id = p_position_id
        or (cycle_id = p_cycle_id and occ_symbol = p_occ_symbol));
    insert into public.option_settlement_materializations(
      economic_event_key, option_position_id, event_kind,
      assigned_stock_position_id, materialized_at
    ) values (
      economic_key, p_position_id, event_kind, stock_position_id, p_occurred_at
    ) returning * into materialization;
    newly_materialized := true;
  end if;

  insert into public.option_settlement_events(
    activity_id, activity_type, economic_event_key, cycle_id, option_position_id,
    assigned_stock_position_id, occ_symbol, underlying, shares, cash_effect, occurred_at
  ) values (
    p_activity_id, p_activity_type, economic_key, p_cycle_id, p_position_id,
    stock_position_id, p_occ_symbol, p_underlying, p_shares, p_cash_effect, p_occurred_at
  );
  insert into public.option_lifecycle_events(
    id, cycle_id, option_position_id, event_type, state, reason,
    sanitized_details, occurred_at
  ) values (
    gen_random_uuid(), p_cycle_id, p_position_id,
    'option.activity.' || lower(p_activity_type),
    case when event_kind = 'assignment' then 'assigned' else 'expired' end,
    case when event_kind = 'assignment' then 'alpaca_assignment_or_linked_option_trade'
         else 'alpaca_otm_expiration' end,
    jsonb_build_object(
      'underlying_shares', p_shares,
      'materialized_once', newly_materialized
    ),
    p_occurred_at
  );
  return true;
end;
$$;
revoke execute on function public.record_option_settlement(
  text,uuid,uuid,text,text,text,integer,numeric,timestamptz
) from public, anon, authenticated;
grant execute on function public.record_option_settlement(
  text,uuid,uuid,text,text,text,integer,numeric,timestamptz
) to service_role;

create view public.public_option_cycle_envelopes
with (security_invoker = true) as
select c.id as cycle_id, c.options_capability_status as capability_status,
  (select e.occ_symbol from public.option_candidate_evaluations e
   where e.cycle_id = c.id and e.selected limit 1) as selected_contract,
  coalesce((select jsonb_agg(e.sanitized_evaluation order by e.evaluated_at)
    from public.option_candidate_evaluations e where e.cycle_id = c.id), '[]'::jsonb) as evaluations,
  coalesce((select jsonb_agg(jsonb_build_object(
    'order_id', o.id, 'cycle_id', o.cycle_id, 'option_position_id', o.option_position_id,
    'occ_symbol', o.symbol, 'underlying', o.underlying_symbol,
    'position_intent', o.position_intent, 'status', o.status, 'quantity', o.quantity,
    'filled_quantity', o.filled_quantity, 'average_fill_price', o.average_fill_price,
    'observed_at', o.observed_at
  ) order by o.observed_at) from public.global_orders o
    where o.cycle_id = c.id and o.asset_class = 'option'), '[]'::jsonb) as orders,
  coalesce((select jsonb_agg(jsonb_build_object(
    'position_id', p.id, 'cycle_id', p.cycle_id, 'occ_symbol', p.occ_symbol,
    'underlying', p.underlying_symbol, 'sector', p.sector, 'contracts', p.contracts,
    'strike', p.strike, 'expiration', p.expiration,
    'entry_credit_per_share', p.entry_credit_per_share,
    'entry_credit_total', p.entry_credit_total, 'collateral', p.collateral,
    'status', p.status, 'opened_at', p.opened_at, 'updated_at', p.updated_at,
    'closed_at', p.closed_at, 'exit_reason', p.exit_reason
  ) order by p.opened_at) from public.option_positions p where p.cycle_id = c.id), '[]'::jsonb) as positions,
  coalesce((select jsonb_agg(jsonb_build_object(
    'event_id', e.id, 'cycle_id', e.cycle_id, 'option_position_id', e.option_position_id,
    'event_type', e.event_type, 'state', e.state, 'reason', e.reason,
    'sanitized_details', e.sanitized_details, 'occurred_at', e.occurred_at
  ) order by e.occurred_at) from public.option_lifecycle_events e where e.cycle_id = c.id), '[]'::jsonb) as events,
  coalesce((select jsonb_agg(jsonb_build_object(
    'activity_id', s.activity_id, 'cycle_id', s.cycle_id,
    'option_position_id', s.option_position_id, 'activity_type', s.activity_type,
    'occ_symbol', s.occ_symbol, 'underlying', s.underlying, 'shares', s.shares,
    'cash_effect', s.cash_effect, 'occurred_at', s.occurred_at
  ) order by s.occurred_at) from public.option_settlement_events s where s.cycle_id = c.id), '[]'::jsonb) as settlements
from public.global_cycles c;
revoke all on table public.public_option_cycle_envelopes
  from public, anon, authenticated, service_role;
grant select on table public.public_option_cycle_envelopes to service_role;

create view public.internal_option_cycle_envelopes
with (security_invoker = true) as
select c.id as cycle_id, c.options_capability_status as capability_status,
  (select e.occ_symbol from public.option_candidate_evaluations e
   where e.cycle_id = c.id and e.selected limit 1) as selected_contract,
  coalesce((select jsonb_agg(e.sanitized_evaluation order by e.evaluated_at)
    from public.option_candidate_evaluations e where e.cycle_id = c.id), '[]'::jsonb) as evaluations,
  coalesce((select jsonb_agg(jsonb_build_object(
    'order_id', o.id, 'cycle_id', o.cycle_id, 'option_position_id', o.option_position_id,
    'intent_key', o.intent_key, 'client_order_id', o.client_order_id,
    'occ_symbol', o.symbol, 'underlying', o.underlying_symbol,
    'position_intent', o.position_intent, 'status', o.status, 'quantity', o.quantity,
    'filled_quantity', o.filled_quantity, 'average_fill_price', o.average_fill_price,
    'broker_order_id', o.broker_order_id, 'observed_at', o.observed_at
  ) order by o.observed_at) from public.global_orders o
    where o.cycle_id = c.id and o.asset_class = 'option'), '[]'::jsonb) as orders,
  coalesce((select jsonb_agg(jsonb_build_object(
    'position_id', p.id, 'cycle_id', p.cycle_id, 'occ_symbol', p.occ_symbol,
    'underlying', p.underlying_symbol, 'sector', p.sector, 'contracts', p.contracts,
    'strike', p.strike, 'expiration', p.expiration,
    'entry_credit_per_share', p.entry_credit_per_share,
    'entry_credit_total', p.entry_credit_total, 'collateral', p.collateral,
    'status', p.status, 'opened_at', p.opened_at, 'updated_at', p.updated_at,
    'closed_at', p.closed_at, 'exit_reason', p.exit_reason
  ) order by p.opened_at) from public.option_positions p where p.cycle_id = c.id), '[]'::jsonb) as positions,
  coalesce((select jsonb_agg(jsonb_build_object(
    'event_id', e.id, 'cycle_id', e.cycle_id, 'option_position_id', e.option_position_id,
    'event_type', e.event_type, 'state', e.state, 'reason', e.reason,
    'sanitized_details', e.sanitized_details, 'occurred_at', e.occurred_at
  ) order by e.occurred_at) from public.option_lifecycle_events e where e.cycle_id = c.id), '[]'::jsonb) as events,
  coalesce((select jsonb_agg(jsonb_build_object(
    'activity_id', s.activity_id, 'cycle_id', s.cycle_id,
    'option_position_id', s.option_position_id, 'activity_type', s.activity_type,
    'occ_symbol', s.occ_symbol, 'underlying', s.underlying, 'shares', s.shares,
    'cash_effect', s.cash_effect, 'occurred_at', s.occurred_at
  ) order by s.occurred_at) from public.option_settlement_events s where s.cycle_id = c.id), '[]'::jsonb) as settlements
from public.global_cycles c;
revoke all on table public.internal_option_cycle_envelopes
  from public, anon, authenticated, service_role;
grant select on table public.internal_option_cycle_envelopes to service_role;
comment on table public.options_capability_checks is
  'Sanitized read-only Paper options capability results; exact balances and account IDs are forbidden.';
comment on table public.option_contract_observations is
  'Sanitized Alpaca Options Data observations. IV relative signal is not IV Rank.';
comment on table public.collateral_reservations is
  'Serialized Cash-Secured Put collateral reservations measured as strike times 100.';
