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

## Implemented Phase 2 request flow

```text
Authenticated browser request
  -> Next.js server proxy (HttpOnly Supabase access token)
  -> FastAPI bearer verification
  -> persistent job
  -> cached SEC + Alpaca + Alpha Vantage reads
  -> deterministic normalization, criteria, clustering, and valuation
  -> owner-scoped snapshots, evidence, watchlist, and audit rows
  -> typed response
```

The analysis service has no order dependency. Provider failures are sanitized at the API boundary, scarce-provider budget is reserved atomically before a cache miss, and stale or missing required data cannot become trade eligible.

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

## Global public cycle

`POST /v1/cycles/activate` atomically creates or returns a cycle keyed by strategy version, mode, applicable US market session, and relevant-data cutoff. Postgres uniqueness is the idempotency boundary. `GET /v1/cycles/{cycle_id}`, `/events`, and `/latest` expose only sanitized envelopes. Provider reservations and Paper `client_order_id` values are durable, so retries and server restarts cannot duplicate consumption or orders. Public visitors never receive direct table access; the FastAPI service uses the server-only secret key and returns an allowlisted DTO.

## Paper order lifecycle

The execution service depends on a small asynchronous broker protocol. Production construction imports the installed `alpaca-py` package and binds the protocol to its trading client only after an exact Paper endpoint check. The network-free `FakeBroker` exists exclusively in `apps/api/tests/fakes` and is not shipped in the application wheel. Public routes are observation-only and never accept an order command. Entry submission requires the complete deterministic preflight decision; auto-execution defaults to disabled and, when enabled, calls the same guarded and idempotent submission path.

Before submission, the service atomically reserves a global order intent in Postgres. The stable `client_order_id` is then queried before submit and reused after timeouts, ambiguous responses, or process restarts. Reconciliation stores cumulative entry and exit fills separately, derives held quantity from those totals, and records each broker snapshot. A closing-order transition must cancel and reconcile the previous close as canceled before a replacement can be reserved; a partial unique index is the database backstop against overlap.

`global_positions`, `global_orders`, `global_order_events`, `global_approval_requests`, and `global_audit_events` are backend-only global lifecycle tables. They use explicit service-role grants, RLS with no visitor policies, immutable event triggers, and sanitized payloads. FastAPI maps them to allowlisted `/v1/cycles/{cycle_id}/orders`, `/approvals`, and `/audit` responses that omit client order IDs, broker IDs, account data, provider payloads, headers, and secrets.

## Phase 3B Options boundaries

`OptionsGateway` is a read-only account/data boundary backed in production by installed `alpaca-py`: Trading account capability and contracts, Alpaca Options Data chains/snapshots with OPRA-to-indicative feed discovery, positions, and Paper account activities. The existing `Broker` protocol owns Paper commands and maps one-contract Market/Day `sell_to_open` and `buy_to_close` requests to alpaca-py position intents. Test doubles remain under `apps/api/tests/fakes` only.

The mode-aware cycle, candidate evaluation, collateral reservation, global order, option position, lifecycle event, and settlement records share one account-wide risk boundary. Entry and close reservations use database functions and stable client order IDs. OPASN, OPTRD, and OPEXP processing locks the position, records the provider event once, changes lifecycle state, and releases collateral atomically.

The runtime API is the application integration path. Alpaca Market and Options Data supply observations; Alpaca Trading supplies the Paper account and execution. Trading MCP is a separate read-only verification/demo surface, while Alpaca CLI is a separate operator smoke-test surface. Neither MCP nor CLI bypasses runtime deterministic controls or becomes a hidden production dependency.