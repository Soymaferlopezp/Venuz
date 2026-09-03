begin;

select plan(19);

select has_table('public', 'estimate_snapshots', 'estimate snapshots exist');
select has_table('public', 'market_snapshots', 'market snapshots exist');
select has_table('public', 'ratio_observations', 'ratio observations exist');
select has_table('public', 'watchlists', 'watchlists exist');
select has_table('public', 'broker_accounts', 'redacted broker accounts exist');
select has_table('public', 'risk_snapshots', 'risk snapshots exist');
select has_table('public', 'provider_cache_entries', 'provider cache exists');
select has_table('public', 'analysis_snapshots', 'canonical analysis snapshots exist');
select has_table('public', 'watchlist_snapshots', 'canonical watchlist snapshots exist');
select has_function(
  'public',
  'reserve_provider_budget',
  array['uuid', 'text', 'date', 'integer'],
  'atomic provider budget function exists'
);
select ok(
  not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname in (
        'estimate_snapshots', 'market_snapshots', 'ratio_observations', 'watchlists',
        'watchlist_items', 'broker_accounts', 'risk_snapshots',
        'provider_cache_entries', 'analysis_snapshots', 'watchlist_snapshots'
      )
      and not c.relrowsecurity
  ),
  'all operational tables have RLS enabled'
);
select ok(not has_table_privilege('anon', 'public.watchlists', 'SELECT'), 'anon cannot read watchlists');
select ok(has_table_privilege('authenticated', 'public.watchlists', 'SELECT'), 'authenticated can read owned watchlists');
select ok(not has_table_privilege('authenticated', 'public.broker_accounts', 'UPDATE'), 'browser cannot mutate broker metadata');
select ok(
  not has_table_privilege('anon', 'public.provider_cache_entries', 'SELECT'),
  'anon cannot read provider cache'
);
select ok(
  not has_table_privilege('authenticated', 'public.provider_cache_entries', 'SELECT'),
  'browser cannot read backend provider cache'
);
select ok(
  has_table_privilege('authenticated', 'public.analysis_snapshots', 'SELECT'),
  'authenticated can read owned analysis snapshots'
);
select ok(
  not has_table_privilege('authenticated', 'public.analysis_snapshots', 'UPDATE'),
  'browser cannot mutate analysis snapshots'
);
select ok(
  has_table_privilege('service_role', 'public.provider_cache_entries', 'INSERT'),
  'backend can populate provider cache'
);

select * from finish();
rollback;
