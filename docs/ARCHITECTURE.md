# Architecture

## System view

```text
Browser
  |
  v
Next.js web on Vercel
  |  authenticated HTTPS
  v
FastAPI service on Render Free
  |------ Supabase Postgres/Auth (state, RLS, audit)
  |------ Alpaca Paper Trading API (orders/account/positions)
  |------ Alpaca Market Data + News
  |------ SEC EDGAR (fundamental facts/filings)
  |------ Alpha Vantage (estimates/revisions only)
  |------ Gemini (primary explanation)
  `------ OpenRouter fixed free model (fallback explanation)

Developer/operator verification
  |------ Alpaca Trading MCP (official paper connection)
  `------ Alpaca CLI (paper smoke tests)
```

## Why two applications

- Next.js focuses on a polished, accessible judge/operator interface and deploys naturally to Vercel.
- FastAPI hosts Python financial/data libraries, Alpaca integration, deterministic calculations, orchestration, and OpenAPI contracts.
- Hosted Supabase persists cross-service state, approvals, audit events, cache metadata, and auth for development, integration, and demonstration.

## Suggested repository layout

```text
apps/
  web/
    src/app/
    src/components/
    src/lib/
    tests/
  api/
    app/
      api/
      core/
      domain/
      integrations/
      services/
      repositories/
    tests/
supabase/
  migrations/
  tests/
docs/
.github/
```

## Backend domain modules

- `universe`: eligible assets, classifications, market cap/liquidity filters.
- `fundamentals`: normalized SEC facts and four-year comparisons.
- `estimates`: Alpha Vantage budget/cache and estimate signals.
- `valuation`: historical ratio cluster, confidence, target range, quarterly freeze.
- `screening`: traffic lights and watchlist ranking.
- `portfolio`: cash, position, and sector exposure.
- `risk`: entry/exit invariants and R calculations.
- `orders`: Alpaca Paper commands and remote reconciliation.
- `approvals`: independent nonblocking decisions and expiry.
- `evidence`: SEC/company/news provenance and citations.
- `agents`: explanation-only LLM orchestration with schema validation.
- `audit`: immutable event trail.

## Data-source ownership

| Data | Primary source | Fallback/notes |
|---|---|---|
| Tradable assets/account/orders/positions | Alpaca | No alternative broker in MVP |
| Quotes/bars/calendar | Alpaca Market Data | Cache short-lived |
| News | Alpaca News/Benzinga | Evidence aid, not authoritative statements |
| Statements/facts | SEC EDGAR | Company filing link retained |
| Analyst estimates/revisions | Alpha Vantage | 25-request hard daily budget |
| Explanation | Gemini | Fixed OpenRouter free model fallback |
| Rules/calculations | Python domain code | No LLM fallback |

## Alpaca API, MCP, and CLI roles

- Trading API/`alpaca-py`: application runtime and source of truth for account/order state.
- Official Trading MCP: required agent/operator integration demonstration against Paper; used to inspect and exercise supported Alpaca tools without replacing deterministic runtime controls.
- Alpaca CLI: reproducible paper smoke tests and operational diagnosis (`profile`, account, assets, orders). Commands and outputs must be documented and sanitized.

This separation avoids pretending MCP/CLI are hidden runtime dependencies while still integrating and demonstrating all required Alpaca surfaces.

## Database model outline

Expected entities, refined through migrations:

- `profiles`, `app_roles`.
- `companies`, `securities`, `sectors`.
- `financial_periods`, `financial_facts`, `estimate_snapshots`.
- `market_snapshots`, `ratio_observations`, `valuation_snapshots`.
- `screening_runs`, `screening_results`, `criterion_results`.
- `watchlists`, `watchlist_items`.
- `opportunities`, `approval_requests`.
- `broker_accounts` (redacted metadata only), `positions`, `orders`, `order_events`.
- `risk_snapshots`, `evidence_items`, `provider_usage`.
- `audit_events`, `job_runs`.

Do not store provider secrets in these tables.

## Job execution on free infrastructure

Render Free sleeps after inactivity and does not provide a free background worker. Therefore:

- The UI always supports manual scan/demo execution.
- Long work is modeled as persistent jobs and can be advanced by authenticated HTTP calls.
- Scheduling may use GitHub Actions or an approved free scheduler, but it is not allowed to be the only way the demo works.
- Provider calls are cached and resumable so a cold start or quota failure does not corrupt state.

## Deployment constraints

### Vercel

- Deploy `apps/web`.
- Configure only publishable browser values as `NEXT_PUBLIC_*`.
- Server-only web values must remain unprefixed.

### Render

- Deploy `apps/api` as a Python web service.
- Bind `0.0.0.0:$PORT`.
- Provide lightweight `GET /health`.
- Expect cold starts and surface a friendly waking state in the web UI.

### Supabase

- Use publishable and secret keys, not new legacy-key setup.
- Explicit grants plus RLS.
- Version schema in `supabase/migrations` and test policies.
- Developer workstations never host a Supabase instance and do not require Docker, Podman, or WSL.
- Link the hosted development project with `supabase link`; inspect `migration list`, preview `db push --dry-run`, apply `db push` only after review, then run `db lint --linked --level error`.
- `db reset --linked` is forbidden. `supabase start` and `db reset --local` are reserved exclusively for the ephemeral GitHub Actions runner.
- pgTAP executes only in validation CI against that ephemeral runner database, never against the shared hosted project.
- Hosted migration deployment is a separate manual workflow protected by the `supabase-development` GitHub environment, concurrency control, timeout, and repository secrets.
