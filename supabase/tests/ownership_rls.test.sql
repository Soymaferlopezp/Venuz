begin;

select plan(4);

set local session_replication_role = replica;
insert into public.profiles (user_id, display_name) values
  ('00000000-0000-0000-0000-000000000001', 'Operator One'),
  ('00000000-0000-0000-0000-000000000002', 'Operator Two');
set local session_replication_role = origin;

insert into public.job_runs (owner_id, job_type, status, idempotency_key) values
  ('00000000-0000-0000-0000-000000000001', 'scan', 'queued', 'operator-one-scan'),
  ('00000000-0000-0000-0000-000000000002', 'scan', 'queued', 'operator-two-scan');

set local role authenticated;
set local request.jwt.claim.sub = '00000000-0000-0000-0000-000000000001';

select is((select count(*) from public.job_runs), 1::bigint, 'operator sees only owned jobs');
select is_empty(
  $$ select id from public.job_runs where owner_id = '00000000-0000-0000-0000-000000000002' $$,
  'cross-user rows are denied by RLS'
);
select results_eq(
  $$ update public.profiles set display_name = 'Updated' where user_id = '00000000-0000-0000-0000-000000000001' returning display_name $$,
  $$ values ('Updated'::text) $$,
  'operator can update own profile'
);
select is_empty(
  $$ update public.profiles set display_name = 'Blocked' where user_id = '00000000-0000-0000-0000-000000000002' returning user_id $$,
  'operator cannot update another profile'
);

reset role;
select * from finish();
rollback;
