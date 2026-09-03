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
alter table public.orders add column cycle_id uuid references public.global_cycles(id) on delete restrict;
alter table public.orders add column client_order_id text;
alter table public.orders add constraint orders_cycle_client_order_key unique (cycle_id, client_order_id);
create index global_cycles_state_updated_idx on public.global_cycles (state, updated_at desc);
create index global_cycle_events_cycle_time_idx on public.global_cycle_events (cycle_id, occurred_at);
create index orders_cycle_id_idx on public.orders (cycle_id);
alter table public.global_cycles enable row level security;
alter table public.global_cycle_events enable row level security;
alter table public.global_provider_budgets enable row level security;
revoke all on table public.global_cycles, public.global_cycle_events, public.global_provider_budgets from public, anon, authenticated, service_role;
grant select, insert, update on table public.global_cycles, public.global_provider_budgets to service_role;
grant select, insert on table public.global_cycle_events to service_role;
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
