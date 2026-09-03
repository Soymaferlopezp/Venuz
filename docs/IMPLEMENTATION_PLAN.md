# Three-Day MVP Implementation Plan

The plan favors a complete, demonstrable vertical slice over broad but incomplete features.

## Day 1 — Foundation and deterministic analysis

### Phase 0: repository foundation

- Scaffold `apps/web`, `apps/api`, and `supabase`.
- Pin dependencies and commit lockfiles.
- Configure linting, formatting, type checks, tests, and CI.
- Add safe config validation and paper-only startup guard.
- Create health/readiness endpoints.

Exit gate: both apps run locally, CI is green, no secret is committed, and a bad/live Alpaca URL fails safely.

### Phase 1: database and auth

- Create initial Supabase migrations, explicit grants, RLS, indexes, and seed/demo operator.
- Use hosted Supabase for development, integration, and demonstration; link and inspect the remote project without running a local stack on developer machines.
- Validate all migrations and the three pgTAP suites from scratch on an ephemeral Supabase stack in GitHub Actions.
- Implement authenticated web/API boundary.
- Persist job, screening, approval, order, evidence, provider-budget, and audit state.

Exit gate: CI pgTAP proves anonymous and cross-user access is denied on an ephemeral database; `migration list` and `db push --dry-run` are reviewed before any manual hosted push; operator paths work.

### Phase 2: data ingestion and domain engine

- Implement Alpaca asset/market/calendar/news clients.
- Implement SEC submissions/company-facts client and normalized financial facts.
- Implement Alpha Vantage estimate client with 25/day hard budget and caching.
- Implement pure criterion, cluster, valuation, traffic-light, and quarterly-freeze functions.

Exit gate: deterministic fixtures cover all formulas and edge cases; one company thesis is reproducible.

Implemented: read-only SEC, Alpaca, and Alpha Vantage adapters; persistent cache and daily budget; deterministic criteria and valuation; quarterly freeze; authenticated analysis/watchlist/provider endpoints; connected minimum web views; and owner-scoped persistence. The approved providers do not yet supply a reliable future earnings date, so provider analyses fail safe to `NO_TRADE` when it is unavailable.

## Day 2 — Portfolio, orders, agent, and UI

### Phase 3: screening and portfolio risk

- Universe filters, sector classification, 10–15 watchlist, portfolio limits, earnings window, freshness, and ranking.
- Persist scan jobs and results with nonblocking progress.

Exit gate: a fixture scan produces explainable candidates and `NO_TRADE` reasons.

### Phase 4: Alpaca paper execution

- Order preview and revalidation.
- Paper market entry, fill reconciliation, initial stop, fair-price branch, +2R branch, 5% trailing, and fundamental exits.
- Idempotency and independent approvals.
- Official Alpaca MCP setup/smoke-test guide and Alpaca CLI smoke tests.

Exit gate: paper test proves order lifecycle or a sanitized fixture simulates it when market timing prevents a live paper fill.

### Phase 5: AI explanation

- Gemini primary, fixed OpenRouter free fallback.
- Strict input minimization and validated output envelope.
- AI explains existing calculations/evidence only.

Exit gate: disabling both LLMs leaves the deterministic app fully usable.

### Phase 6: web experience

- Implement the required screens from `PRODUCT_SPEC.md`.
- Add stale/error/empty/loading/cold-start states.
- Add charts with table/text alternatives and a persistent Paper banner.

Exit gate: Playwright covers scan → thesis → approval/order preview → portfolio/audit.

## Day 3 — Integration, deployment, and presentation

### Phase 7: deployment

- Deploy web to Vercel, API to Render Free, database/auth to Supabase.
- Configure secrets only in platform settings.
- Deploy hosted Supabase migrations only through the manual, protected workflow after reviewing its dry-run. Never use `db reset --linked`, automated `migration repair`, or automated `db pull`.
- Configure Render `/health`, CORS, Vercel API URL, and Supabase redirect URLs.
- Validate cold-start behavior.

### Phase 8: hardening and documentation

- Run security scans, database advisors, full tests, production builds, and paper smoke tests.
- Finalize README, architecture diagram, API docs, troubleshooting, limitations, and demo script.
- Capture sanitized screenshots/video only after rotating any accidentally exposed key.

Exit gate: a judge can understand and reproduce the demo from README.

## De-scope order if time runs short

Keep, in order:

1. Deterministic strategy and evidence.
2. Alpaca Paper order lifecycle.
3. Portfolio/risk guards and audit.
4. Functional dashboard/company/approval/portfolio screens.
5. MCP and CLI verification documentation.

Defer first:

- Fancy animations.
- Broad scheduler automation.
- Multiple user roles.
- Options trading.
- Additional providers.
- Complex backtesting.

## Phase 3 execution amendment

For this delivery, the official Phase 3 scope supersedes the older phase labels above: public global activation, screening/portfolio preflight, durable provider controls, and the Alpaca Paper execution contract are one vertical slice. Exit gate: concurrent activations converge on one cycle; every deterministic guard is tested; public responses are sanitized; and all order lifecycle tests use fakes with zero external submissions.

## Phase 3 second-slice checkpoint

Implemented locally: broker protocol and Paper-only `alpaca-py` adapter; mandatory fake-broker tests; durable idempotent submission; partial/full fill processing; restart reconciliation; initial 10% stop; +2R and estimated-price branches; 5% trailing protection while retaining the full position; cancel-confirm-replace enforcement; critical automatic exits; independent noncritical-red approvals; sanitized observation endpoints; and complete durable audit records.

The schema expansion remains in the unapplied `20260903043000_phase3_global_cycles.sql` migration because that migration has never reached the hosted project. It also removes an invalid duplicate `client_order_id` alteration inherited from the first slice. Do not create a follow-up migration unless the Phase 3 migration is applied first. The hosted preview, apply, deployment, and Paper smoke test are separate approval gates.
