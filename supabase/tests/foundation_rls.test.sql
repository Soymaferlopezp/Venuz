begin;

select plan(14);

select has_table('public', 'profiles', 'profiles exists');
select has_table('public', 'provider_budgets', 'provider budgets exist');
select has_table('public', 'screening_runs', 'screening runs exist');
select has_table('public', 'approval_requests', 'approvals exist');
select has_table('public', 'orders', 'orders exist');
select has_table('public', 'audit_events', 'audit events exist');
select ok(
  (select relrowsecurity from pg_class where oid = 'public.profiles'::regclass),
  'profiles has RLS enabled'
);
select ok(
  not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relkind = 'r'
      and not c.relrowsecurity
      and c.relname in (
        'profiles', 'app_roles', 'sectors', 'companies', 'provider_budgets', 'job_runs',
        'financial_facts', 'valuation_snapshots', 'screening_runs', 'screening_results',
        'criterion_results', 'opportunities', 'approval_requests', 'positions', 'orders',
        'order_events', 'evidence_items', 'audit_events'
      )
  ),
  'all exposed application tables have RLS enabled'
);
select ok(not has_table_privilege('anon', 'public.profiles', 'SELECT'), 'anon cannot read profiles');
select ok(not has_table_privilege('anon', 'public.companies', 'SELECT'), 'anon cannot read catalog');
select ok(has_table_privilege('authenticated', 'public.companies', 'SELECT'), 'authenticated reads catalog');
select ok(not has_table_privilege('authenticated', 'public.orders', 'INSERT'), 'browser cannot insert orders');
select ok(not has_table_privilege('service_role', 'public.audit_events', 'UPDATE'), 'audit cannot be updated');
select trigger_is(
  'public', 'audit_events', 'audit_events_immutable', 'public', 'reject_audit_mutation',
  'audit immutability trigger is installed'
);

select * from finish();
rollback;
