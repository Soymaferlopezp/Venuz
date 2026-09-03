# Venuz

> Evidence-first fundamental screening for US equities, designed exclusively for Alpaca Paper Trading.

Venuz turns SEC filings, Alpaca market data, and narrowly scoped analyst estimates into a deterministic company thesis. Every criterion, valuation observation, exclusion, and state transition is reproducible and auditable. An LLM is never allowed to decide eligibility, risk, valuation, or trading actions.

> **PAPER TRADING - NO REAL MONEY.** Venuz is not financial advice and does not guarantee future results.

## Phase 2 status

The current vertical slice is functional:

- authenticated Next.js screens for the screener, company thesis, and provider budget;
- a FastAPI analysis API with Supabase Auth bearer verification;
- SEC Company Facts and Submissions ingestion;
- read-only Alpaca assets, snapshots, daily bars, exchange calendar, and news adapters;
- Alpha Vantage estimates and revisions with an atomic 25-request UTC daily budget;
- deterministic universe filters, seven criteria, historical P/E and P/FCF clustering, valuation ranges, and quarterly freezing;
- persistent provider cache, analyses, criteria, evidence, ratios, watchlists, jobs, and audit events;
- explicit grants, owner-scoped RLS, and backend-only privileged writes.

There are no order endpoints in Phase 2, and no Alpaca order is sent.

## Architecture

```text
Browser
  -> Next.js on Vercel
       -> server session route -> Supabase Auth
       -> authenticated server proxy
            -> FastAPI on Render
                 -> Supabase Postgres (RLS, cache, analysis, audit)
                 -> SEC EDGAR (fundamentals and filing history)
                 -> Alpaca Paper/Market Data (read-only in Phase 2)
                 -> Alpha Vantage (estimates and revisions only)
```

The browser never receives provider or database secret keys. Financial rules and monetary calculations live in Python and use `Decimal`; persisted timestamps use UTC. Invalid, stale, missing, or contradictory required data defaults to `NO_TRADE`.

See [the trading strategy](docs/TRADING_STRATEGY.md), [product specification](docs/PRODUCT_SPEC.md), [architecture](docs/ARCHITECTURE.md), and [security controls](docs/SECURITY_AND_SECRETS.md).

## Deterministic analysis

The engine evaluates:

1. four-year revenue trend;
2. positive net income and net-margin trend;
3. free cash flow, defined as operating cash flow minus capital expenditure, positive in at least three of four years and in the latest year;
4. positive latest shareholders' equity, defined as assets minus liabilities;
5. debt/equity below 1;
6. both forward signals: consensus EPS above its previous estimate and expected EPS above the comparable prior period;
7. self-relative valuation using separate P/E and P/FCF estimates.

The valuation engine excludes the current quarter, records included and excluded observations with reasons, selects a deterministic coherent cluster from the prior eight completed quarters, and uses its median. P/E and P/FCF target prices are never averaged. The lower result is the floor, the higher result is the ceiling, and the documented safety margin determines green states.

A valid range is recalculated only after two complete US sessions following a report and remains frozen for the quarter. A purchase is blocked in the five sessions before a known earnings date. Because the currently approved sources do not provide a reliable future earnings calendar, an unavailable next date is explicitly persisted as `next_earnings_schedule_unavailable` and keeps the result at `NO_TRADE`.

## Requirements

- Windows Command Prompt (`cmd.exe`)
- Node.js 22+
- Python 3.12
- Git
- access to a hosted Supabase project
- paper Alpaca credentials, a descriptive SEC User-Agent, and an Alpha Vantage key for real provider analysis

No local Supabase runtime, Docker, Podman, or WSL is used on developer machines.

## Environment setup

Use [`.env.example`](.env.example) as the inventory of variable names. Never commit populated environment files.

- Create `apps/api/.env` with server-only values.
- Create `apps/web/.env.local` with only:
  - `NEXT_PUBLIC_APP_NAME`
  - `NEXT_PUBLIC_API_BASE_URL`
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

The API refuses to start unless these safety settings remain in force:

```text
TRADING_MODE=paper
ALPACA_PAPER=true
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets
AUTO_EXECUTION_ENABLED=false
```

## Run locally with Command Prompt

API:

```bat
cd apps\api
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Web, in another Command Prompt:

```bat
cd apps\web
npm ci
npm run dev
```

Open `http://localhost:3000/sign-in`, sign in with a Supabase Auth user, open the screener, and run the provider-backed scan. Render Free cold starts are surfaced as a waiting state in the UI.

To verify the real SEC and Alpaca read-only contracts without displaying credentials or touching orders:

```bat
cd apps\api
.venv\Scripts\python.exe scripts\provider_read_smoke.py
```

Fixture mode is available only outside production for deterministic development and tests:

```text
POST /v1/analysis/AAPL
{"mode":"fixture"}
```

## Authenticated API

All Phase 2 routes require a valid Supabase bearer token:

- `POST /v1/analysis/{symbol}`
- `GET /v1/analysis/{symbol}/latest`
- `GET /v1/analysis/{symbol}/criteria`
- `GET /v1/analysis/{symbol}/valuation`
- `GET /v1/analysis/{symbol}/evidence`
- `POST /v1/watchlists/build?mode=provider`
- `GET /v1/watchlists/latest`
- `GET /v1/providers/status`

The watchlist scan analyzes the reviewed Phase 2 universe, applies the documented eligibility filters, ranks results deterministically, and persists ten companies. No endpoint creates, previews, or submits an order.

## Hosted Supabase migrations

The hosted project is the official database runtime. Review every versioned migration from Command Prompt:

```bat
npx --yes supabase@2.116.0 login
npx --yes supabase@2.116.0 link --project-ref PROJECT_REF
npx --yes supabase@2.116.0 migration list
npx --yes supabase@2.116.0 db push --dry-run
```

After explicit review:

```bat
npx --yes supabase@2.116.0 db push
npx --yes supabase@2.116.0 migration list
npx --yes supabase@2.116.0 db lint --linked --level error
```

Never run `supabase db reset --linked`. Do not automate `migration repair` or `db pull`. pgTAP runs only against the ephemeral Supabase stack created by GitHub Actions.

## Verification

Backend:

```bat
cd apps\api
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy app tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m build --wheel
.venv\Scripts\python.exe -m pip check
```

Frontend:

```bat
cd apps\web
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
```

Repository and secret hygiene:

```bat
git diff --check
git check-ignore -v apps\api\.env apps\web\.env.local
git status --short
```

CI additionally runs pgTAP, Gitleaks, dependency checks, and production builds.

## Current limitations

- The Phase 2 universe is a reviewed ten-company shortlist, not a broad-market discovery service.
- A reliable next earnings date is not available from the approved runtime sources, so a provider result remains `NO_TRADE` when that date is unknown.
- Provider-backed analysis requires configured external credentials and consumes Alpha Vantage budget only on a cache miss.
- AI explanation is intentionally deferred; deterministic results remain fully usable.
- Order lifecycle, portfolio enforcement, Alpaca Trading MCP/CLI execution smoke tests, and paper execution belong to the next phase.
- Render Free can sleep and introduce a cold-start delay.

## Next phase

Phase 3 should add portfolio-state ingestion and entry revalidation first, then the fully idempotent Alpaca Paper order lifecycle. It must preserve the 20% cash floor, 10% position cap, 20% sector cap, two-company sector limit, five-session earnings block, independent approvals, and audit trail before any paper order becomes eligible.
