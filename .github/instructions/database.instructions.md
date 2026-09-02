---
applyTo: "supabase/**/*.{sql,toml}"
---

# Supabase/Postgres instructions

- Use versioned Supabase migrations. Never make an undocumented dashboard-only schema change.
- Use current publishable (`sb_publishable_*`) and secret (`sb_secret_*`) keys; do not introduce legacy `anon`/`service_role` names in new setup.
- Enable RLS on every exposed table. Explicitly grant only required privileges because new tables are not automatically exposed to the Data API.
- Frontend access uses the publishable key plus authenticated JWT and ownership/role policies. The secret key is backend-only and bypasses RLS.
- Never authorize with user-editable `user_metadata`; use server-controlled app metadata or relational role tables.
- UPDATE policies require `USING` and `WITH CHECK`; views exposed to clients use `security_invoker`.
- Prefer UUID primary keys, `timestamptz`, check constraints, foreign keys, unique idempotency keys, and indexes for query paths.
- Preserve immutable audit events; corrections append new events rather than rewriting history.
- Hosted Supabase is the runtime for development, integration, and demonstration. Never require Docker, Podman, WSL, or a local Supabase instance on developer machines.
- Keep migrations in `supabase/migrations`. Link with `supabase link`, review `supabase migration list`, preview with `supabase db push --dry-run`, apply with `supabase db push` only after explicit approval, and validate with `supabase db lint --linked --level error`.
- `supabase db reset --linked` is prohibited. Do not automate `supabase migration repair` or `supabase db pull`.
- `supabase start` and `supabase db reset --local` are allowed only in the ephemeral GitHub Actions database job. Run all three pgTAP suites there, never against the shared hosted project, and always stop the stack.
- Run database advisors and schema/RLS tests before merging.
