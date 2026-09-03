create table public.global_cycles (
  id uuid primary key default gen_random_uuid(), cycle_key text not null unique,
  strategy_version text not null, market_session date not null, data_cutoff timestamptz not null,
  state text not null default 'queued' check (state in ('queued','exploring','analyzing','evaluating_trade','paper_order_submitted','monitoring','completed','blocked','quota_exhausted','provider_unavailable','failed_safe')),
  data_freshness text not null default 'fresh' check (data_freshness in ('fresh','cached','stale')),
  sanitized_inputs jsonb not null default '{}'::jsonb, sanitized_result jsonb not null default '{}'::jsonb,
  blocked_reasons jsonb not null default '[]'::jsonb, evidence_links jsonb not null default '[]'::jsonb,
  provider_provenance jsonb not null default '[]'::jsonb, paper_order_submitted boolean not null default false,
  retry_count integer not null default 0 check (retry_count >= 0), created_at timestamptz not null default now(),
  started_at timestamptz, completed_at timestamptz, updated_at timestamptz not null default now()
);
create table public.global_cycle_events (
  id bigint generated always as identity primary key, cycle_id uuid not null references public.global_cycles(id) on delete cascade,
  state text not null, message text not null, sanitized_payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(), unique (cycle_id, state)
);
create table public.global_provider_budgets (
  provider text not null, budget_date date not null, request_limit integer not null check (request_limit > 0),
  reserved_count integer not null default 0 check (reserved_count between 0 and request_limit),
  updated_at timestamptz not null default now(), primary key (provider, budget_date)
);
create index global_cycles_state_updated_idx on public.global_cycles (state, updated_at desc);
create index global_cycle_events_cycle_time_idx on public.global_cycle_events (cycle_id, occurred_at);
alter table public.global_cycles enable row level security;
alter table public.global_cycle_events enable row level security;
alter table public.global_provider_budgets enable row level security;
revoke all on table public.global_cycles, public.global_cycle_events, public.global_provider_budgets from public, anon, authenticated, service_role;
grant select, insert, update on table public.global_cycles, public.global_provider_budgets to service_role;
grant select, insert on table public.global_cycle_events to service_role;
revoke all on sequence public.global_cycle_events_id_seq from public, anon, authenticated, service_role;
grant usage, select on sequence public.global_cycle_events_id_seq to service_role;
create view public.public_cycle_envelopes with (security_invoker = true) as
select c.id as cycle_id, c.cycle_key, c.state, c.data_freshness, c.paper_order_submitted,
 c.blocked_reasons, c.evidence_links, c.provider_provenance, c.updated_at,
 coalesce(jsonb_agg(jsonb_build_object('state',e.state,'occurred_at',e.occurred_at,'message',e.message) order by e.occurred_at) filter (where e.id is not null),'[]'::jsonb) as events
from public.global_cycles c left join public.global_cycle_events e on e.cycle_id=c.id group by c.id;
revoke all on table public.public_cycle_envelopes from public, anon, authenticated, service_role;
grant select on table public.public_cycle_envelopes to service_role;
create function public.activate_global_cycle(p_cycle_key text, p_now timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare c public.global_cycles; parts text[];
begin
 parts := string_to_array(p_cycle_key, ':');
 if array_length(parts,1) < 4 or length(p_cycle_key)>256 then raise exception 'invalid cycle key'; end if;
 insert into public.global_cycles(cycle_key,strategy_version,market_session,data_cutoff,updated_at)
 values(p_cycle_key,parts[1],parts[2]::date,concat(parts[3],':',parts[4],':',parts[5])::timestamptz,p_now)
 on conflict(cycle_key) do update set cycle_key=excluded.cycle_key returning * into c;
 insert into public.global_cycle_events(cycle_id,state,message,occurred_at) values(c.id,'queued','Cycle queued',p_now) on conflict do nothing;
 return (select to_jsonb(v) from public.public_cycle_envelopes v where v.cycle_id=c.id);
end; $$;
create function public.reserve_global_provider_budget(p_provider text,p_budget_date date,p_request_limit integer)
returns integer language plpgsql security invoker set search_path='' as $$
declare remaining integer;
begin
 insert into public.global_provider_budgets(provider,budget_date,request_limit,reserved_count) values(p_provider,p_budget_date,p_request_limit,1)
 on conflict(provider,budget_date) do update set reserved_count=public.global_provider_budgets.reserved_count+1,
 request_limit=least(public.global_provider_budgets.request_limit,excluded.request_limit),updated_at=now()
 where public.global_provider_budgets.reserved_count<public.global_provider_budgets.request_limit
 returning request_limit-reserved_count into remaining;
 if remaining is null then raise exception 'provider budget exhausted'; end if; return remaining;
end; $$;
revoke execute on function public.activate_global_cycle(text,timestamptz), public.reserve_global_provider_budget(text,date,integer) from public, anon, authenticated;
grant execute on function public.activate_global_cycle(text,timestamptz), public.reserve_global_provider_budget(text,date,integer) to service_role;
create table public.global_positions (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  symbol text not null check (symbol = upper(symbol) and length(symbol) between 1 and 10),
  quantity numeric(28,8) not null check (quantity >= 0),
  entry_filled_quantity numeric(28,8) not null default 0 check (entry_filled_quantity >= 0),
  exit_filled_quantity numeric(28,8) not null default 0 check (exit_filled_quantity >= 0 and exit_filled_quantity <= entry_filled_quantity),
  average_fill_price numeric(20,8) not null check (average_fill_price > 0),
  estimated_price numeric(20,8) check (estimated_price > 0),
  protection_mode text not null default 'initial'
    check (protection_mode in ('initial','estimated_price','trailing','exiting','closed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (cycle_id, symbol)
);

create table public.global_orders (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  position_id uuid references public.global_positions(id) on delete restrict,
  intent_key text not null unique check (length(intent_key) between 1 and 256),
  client_order_id text not null unique check (length(client_order_id) between 1 and 48),
  broker_order_id text unique,
  symbol text not null check (symbol = upper(symbol) and length(symbol) between 1 and 10),
  purpose text not null check (purpose in ('entry','initial_stop','estimated_price_stop','trailing_stop','critical_exit')),
  side text not null check (side in ('buy','sell')),
  order_type text not null check (order_type in ('market','stop','trailing_stop')),
  status text not null default 'pending'
    check (status in ('pending','submitted','partially_filled','filled','canceled','rejected','expired')),
  quantity numeric(28,8) not null check (quantity > 0),
  filled_quantity numeric(28,8) not null default 0 check (filled_quantity between 0 and quantity),
  average_fill_price numeric(20,8) check (average_fill_price > 0),
  stop_price numeric(20,8) check (stop_price > 0),
  trail_percent numeric(8,4) check (trail_percent > 0 and trail_percent <= 100),
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index global_orders_one_active_close_idx
  on public.global_orders (position_id)
  where side = 'sell' and status in ('pending','submitted','partially_filled');
create index global_orders_cycle_observed_idx
  on public.global_orders (cycle_id, observed_at);

create table public.global_order_events (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.global_orders(id) on delete restrict,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  event_type text not null,
  status text not null,
  filled_quantity numeric(28,8) not null,
  average_fill_price numeric(20,8),
  sanitized_payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null,
  unique (order_id, status, filled_quantity, occurred_at)
);
create index global_order_events_cycle_time_idx
  on public.global_order_events (cycle_id, occurred_at);

create table public.global_approval_requests (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  symbol text not null check (symbol = upper(symbol) and length(symbol) between 1 and 10),
  reason_code text not null,
  status text not null default 'pending' check (status in ('pending','approved','rejected','expired')),
  evidence_links jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index global_approvals_cycle_status_idx
  on public.global_approval_requests (cycle_id, status, created_at);

create table public.global_audit_events (
  id uuid primary key,
  cycle_id uuid not null references public.global_cycles(id) on delete restrict,
  event_type text not null,
  symbol text not null,
  decision text not null,
  correlation_id uuid not null,
  sanitized_details jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null
);
create index global_audit_cycle_time_idx
  on public.global_audit_events (cycle_id, occurred_at);

alter table public.global_positions enable row level security;
alter table public.global_orders enable row level security;
alter table public.global_order_events enable row level security;
alter table public.global_approval_requests enable row level security;
alter table public.global_audit_events enable row level security;

revoke all on table public.global_positions, public.global_orders, public.global_order_events,
  public.global_approval_requests, public.global_audit_events from public, anon, authenticated, service_role;
grant select, insert, update on table public.global_positions, public.global_orders,
  public.global_approval_requests to service_role;
grant select, insert on table public.global_order_events, public.global_audit_events to service_role;

create function public.capture_global_order_event()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  insert into public.global_order_events(
    order_id, cycle_id, event_type, status, filled_quantity, average_fill_price,
    sanitized_payload, occurred_at
  ) values (
    new.id, new.cycle_id,
    case when tg_op = 'INSERT' then 'order.reserved' else 'order.reconciled' end,
    new.status, new.filled_quantity, new.average_fill_price,
    jsonb_build_object('purpose', new.purpose, 'order_type', new.order_type),
    new.observed_at
  ) on conflict do nothing;
  return new;
end; $$;

create trigger capture_global_order_event_trigger
after insert or update on public.global_orders
for each row execute function public.capture_global_order_event();

create function public.reject_global_audit_mutation()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  raise exception 'global audit records are immutable';
end; $$;

create trigger global_order_events_immutable
before update or delete on public.global_order_events
for each row execute function public.reject_global_audit_mutation();
create trigger global_audit_events_immutable
before update or delete on public.global_audit_events
for each row execute function public.reject_global_audit_mutation();
revoke execute on function public.capture_global_order_event(),
  public.reject_global_audit_mutation() from public, anon, authenticated;

create function public.reserve_global_order(
  p_order_id uuid, p_cycle_id uuid, p_position_id uuid, p_intent_key text,
  p_client_order_id text, p_symbol text, p_purpose text, p_side text,
  p_order_type text, p_quantity numeric, p_stop_price numeric,
  p_trail_percent numeric, p_observed_at timestamptz
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.global_orders; was_created boolean := true;
begin
  insert into public.global_orders(
    id, cycle_id, position_id, intent_key, client_order_id, symbol, purpose,
    side, order_type, quantity, stop_price, trail_percent, observed_at
  ) values (
    p_order_id, p_cycle_id, p_position_id, p_intent_key, p_client_order_id,
    upper(p_symbol), p_purpose, p_side, p_order_type, p_quantity,
    p_stop_price, p_trail_percent, p_observed_at
  ) on conflict (intent_key) do nothing returning * into o;
  if o.id is null then
    was_created := false;
    select * into strict o from public.global_orders where intent_key = p_intent_key;
  end if;
  if p_purpose = 'critical_exit' then
    if p_position_id is null then
      raise exception 'critical exit requires a position';
    end if;
    update public.global_positions
      set protection_mode = 'exiting', updated_at = p_observed_at
      where id = p_position_id and cycle_id = p_cycle_id;
    if not found then
      raise exception 'critical exit position not found';
    end if;
    insert into public.global_audit_events(
      id, cycle_id, event_type, symbol, decision, correlation_id,
      sanitized_details, occurred_at
    ) values (
      p_order_id, p_cycle_id, 'fundamentals.critical_exit_reserved', upper(p_symbol),
      'automatic_exit', p_order_id, jsonb_build_object('purpose', p_purpose),
      p_observed_at
    ) on conflict (id) do nothing;
  end if;
  return to_jsonb(o) || jsonb_build_object('reservation_created', was_created);
end; $$;

revoke execute on function public.reserve_global_order(
  uuid,uuid,uuid,text,text,text,text,text,text,numeric,numeric,numeric,timestamptz
) from public, anon, authenticated;
grant execute on function public.reserve_global_order(
  uuid,uuid,uuid,text,text,text,text,text,text,numeric,numeric,numeric,timestamptz
) to service_role;
