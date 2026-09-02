begin;

select plan(10);

select has_table('public', 'estimate_snapshots', 'estimate snapshots exist');
select has_table('public', 'market_snapshots', 'market snapshots exist');
select has_table('public', 'ratio_observations', 'ratio observations exist');
select has_table('public', 'watchlists', 'watchlists exist');
select has_table('public', 'broker_accounts', 'redacted broker accounts exist');
select has_table('public', 'risk_snapshots', 'risk snapshots exist');
select ok(
  not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname in (
        'estimate_snapshots', 'market_snapshots', 'ratio_observations', 'watchlists',
        'watchlist_items', 'broker_accounts', 'risk_snapshots'
      )
      and not c.relrowsecurity
  ),
  'all operational tables have RLS enabled'
);
select ok(not has_table_privilege('anon', 'public.watchlists', 'SELECT'), 'anon cannot read watchlists');
select ok(has_table_privilege('authenticated', 'public.watchlists', 'SELECT'), 'authenticated can read owned watchlists');
select ok(not has_table_privilege('authenticated', 'public.broker_accounts', 'UPDATE'), 'browser cannot mutate broker metadata');

select * from finish();
rollback;
