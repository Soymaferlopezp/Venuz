# Phase 1 prompt — foundation, Supabase, and contracts

Read `AGENTS.md` and all `docs/`. Implement only the foundation phases from `docs/IMPLEMENTATION_PLAN.md`.

Deliver:

- Monorepo scaffolding for Next.js web, FastAPI API, and Supabase migrations.
- Pinned dependencies and lockfiles; Node 22+ and Python 3.12+.
- Formatting, lint, typing, tests, and GitHub Actions CI.
- Typed configuration with paper-only startup validation and safe `.env.example` alignment.
- Supabase schema for profiles, providers/budgets, jobs, companies, facts, valuations, screenings, criteria, opportunities, approvals, positions, orders/events, evidence, and audit.
- Explicit grants, RLS, indexes, idempotency keys, immutable audit approach, and database tests.
- Hosted Supabase as the development/integration/demo runtime, with versioned migrations and documented `link` -> `migration list` -> `db push --dry-run` -> approved `db push` -> linked lint flow.
- Three pgTAP suites executed only on an ephemeral Supabase stack in GitHub Actions; no Docker, Podman, WSL, or local Supabase runtime on developer machines.
- Authenticated web/API skeleton plus `/health`.
- README setup and architecture updated with verified commands.

Do not implement provider calls or orders yet. Never use `db reset --linked`; do not automate `migration repair` or `db pull`. Exit only when CI and RLS tests pass and no live Alpaca URL can start the API.
