begin;

select plan(7);

insert into auth.users (
  id,
  email,
  aud,
  role,
  raw_app_meta_data,
  raw_user_meta_data
) values
  (
    '00000000-0000-0000-0000-000000000001',
    'operator-one@example.test',
    'authenticated',
    'authenticated',
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000000002',
    'operator-two@example.test',
    'authenticated',
    'authenticated',
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb
  );

insert into public.profiles (user_id, display_name) values
  ('00000000-0000-0000-0000-000000000001', 'Operator One'),
  ('00000000-0000-0000-0000-000000000002', 'Operator Two');

insert into public.job_runs (owner_id, job_type, status, idempotency_key) values
  ('00000000-0000-0000-0000-000000000001', 'scan', 'queued', 'operator-one-scan'),
  ('00000000-0000-0000-0000-000000000002', 'scan', 'queued', 'operator-two-scan');

set local role authenticated;
set local request.jwt.claims =
  '{"sub":"00000000-0000-0000-0000-000000000001","role":"authenticated","aud":"authenticated"}';

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

set local request.jwt.claims =
  '{"sub":"00000000-0000-0000-0000-000000000002","role":"authenticated","aud":"authenticated"}';

select is((select count(*) from public.job_runs), 1::bigint, 'second operator sees only owned jobs');
select is_empty(
  $$ select id from public.job_runs where owner_id = '00000000-0000-0000-0000-000000000001' $$,
  'second operator cannot read first operator rows'
);
select is_empty(
  $$ update public.profiles set display_name = 'Blocked Again' where user_id = '00000000-0000-0000-0000-000000000001' returning user_id $$,
  'second operator cannot update first operator profile'
);

reset role;
reset request.jwt.claims;
select * from finish();
rollback;
