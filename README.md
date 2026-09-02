# Venuz

> Evidence-first fundamental analysis and risk-controlled execution for **Alpaca Paper Trading**.

This repository is the foundation for a hackathon MVP that discovers high-quality US equities, evaluates them with transparent deterministic rules, explains the evidence with AI, and manages simulated positions through Alpaca.

**Important:** this project is paper trading only. It does not use or require real funds, and it is not financial advice or a production-ready autonomous trading system.

## Why this project is different

Many “trading agents” ask a language model what to buy and hand it broker tools. This project separates responsibilities:

- Deterministic Python code calculates financial metrics, valuation, eligibility, allocation, risk, stops, and order transitions.
- Alpaca provides paper execution, account/position state, market data, news, MCP tools, and CLI operations.
- SEC filings ground company financial statements.
- Alpha Vantage contributes analyst estimates and revisions under a strict free-tier budget.
- Gemini explains structured evidence; OpenRouter is a fixed-model fallback.
- Supabase stores state, approvals, evidence, provider budgets, and an immutable audit trail.
- A human approval queue handles uncertainty without blocking unrelated analysis or trades.

The language model explains decisions; it does not become the trading policy.

## MVP scope

Included:

- US equities.
- Fundamental screening and a 10–15 company watchlist.
- Self-relative P/E and P/FCF valuation.
- Alpaca Paper market orders and protective order lifecycle.
- Portfolio, sector, cash, earnings-window, and data-quality safeguards.
- Evidence timeline, nonblocking approvals, and audit history.
- Responsive judge/operator web application.


## Approved stack

| Layer | Technology | Deployment |
|---|---|---|
| Web | Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, Recharts | Vercel Hobby |
| API/domain engine | Python 3.12+, FastAPI, Pydantic v2 | Render Free web service |
| Database/Auth | Supabase Postgres + Supabase Auth, RLS | Supabase Free |
| Trading/runtime | `alpaca-py`, Alpaca Paper Trading API | FastAPI service |
| Agent tooling | Official Alpaca Trading MCP | Paper connection |
| Operations | Alpaca CLI | Developer/operator machine |
| Statements | SEC EDGAR Company Facts/Submissions | Cached by API |
| Estimates | Alpha Vantage | 25-request/day hard budget |
| AI primary | Gemini Free Tier | Server-side only |
| AI fallback | Fixed OpenRouter free model | Server-side only |
| Tests | pytest, Vitest/RTL, Playwright, SQL/RLS tests | Local + GitHub Actions |

Node.js 22+ is required because current Supabase client libraries no longer support Node.js 20.

## Architecture

```text
User / Judge
    |
    v
Next.js on Vercel
    |
    v
FastAPI on Render Free
    |-- Supabase Postgres/Auth
    |-- Alpaca Paper Trading + Market Data + News
    |-- SEC EDGAR
    |-- Alpha Vantage estimates
    |-- Gemini
    `-- OpenRouter fallback

Codex/operator
    |-- Official Alpaca Trading MCP (Paper)
    `-- Alpaca CLI (Paper smoke tests)
```

See [Architecture](docs/ARCHITECTURE.md) for boundaries, provider ownership, schema outline, and deployment constraints.

## Strategy summary

The complete source of truth is [Trading Strategy](docs/TRADING_STRATEGY.md).

### Universe

- Top 10–20 eligible companies by market capitalization in prioritized sectors.
- At least USD 10B market capitalization.
- At least USD 20M average daily dollar volume.
- Positive latest net income.
- Alpaca-tradable US equity.
- Excludes banks, insurers, REITs, penny stocks, crypto, and unprofitable companies.

### Seven criteria

1. Four-year revenue trend.
2. Net-income and net-margin quality.
3. Free cash flow, positive in at least 3 of 4 years and latest year.
4. Positive/growing shareholders’ equity (`assets - liabilities`).
5. Debt/Equity below 1.
6. Positive comparable EPS expectations and upward estimate revisions.
7. Self-relative P/E and P/FCF valuation.

Every criterion must be green or yellow. Any red blocks entry.

### Valuation

For each ratio, use a coherent cluster from up to eight completed prior quarters and its median:

```text
estimated price = current price × historical ratio / current ratio
```

P/E and P/FCF targets remain separate and form a range. They are recalculated after two complete sessions following earnings and frozen until the next report.

- Strong green: at least 10% below the range floor.
- Green: 5–10% below the range floor.
- Yellow: inside the range or low confidence.
- Red: above the range ceiling.

Only green valuation can authorize an automatic paper entry.

### Portfolio and risk

- Maximum 10% per position.
- Minimum 20% cash.
- Maximum 20% per sector and two companies per sector.
- No entry during the five sessions before earnings.
- Market entry only during regular US hours after deterministic preflight.
- Initial stop 10% below actual fill.
- Benefit:risk = 2:1; initial objective is +2R (approximately +20%).
- At +2R, retain the full position and activate a 5% trailing stop.
- If fair value arrives first, protect 5% below it; at 5% above fair value, protect fair value and trail 5%.

## Product screens

- Judge overview.
- Authentication.
- Portfolio dashboard.
- Screener/watchlist.
- Company thesis and evidence.
- Paper order preview.
- Independent approval queue.
- Positions and exit-state monitoring.
- Orders and audit timeline.
- Integration health/settings with redacted credential status.

See [Product Specification](docs/PRODUCT_SPEC.md) and the [UI generator prompt](docs/UI_GENERATOR_PROMPT.md).

## Repository status

The project is currently in the **specification and operational-foundation phase**. Application scaffolding and implementation follow the phase prompts in `.github/prompts/`.

Planned layout:

```text
apps/
  web/                 # Next.js application
  api/                 # FastAPI and deterministic domain engine
supabase/
  migrations/          # Versioned schema, grants, RLS, indexes
  tests/               # Database/RLS tests
docs/                  # Product and engineering source of truth
.github/
  instructions/        # Scoped agent rules
  prompts/             # Master and phase build prompts
```

The inherited SaludPlus/Laravel material was removed before the initial commit. See the [GitHub folder audit](docs/GITHUB_AUDIT.md) for the cleanup record and the current center of operations.

## Prerequisites

- Git and a GitHub account.
- Node.js 22+ and a package manager selected by the scaffold phase.
- Python 3.12+.
- Supabase CLI (version discovered and pinned during implementation).
- Alpaca CLI.
- Accounts/keys:
  - Alpaca Paper Trading.
  - Supabase.
  - Gemini API Free Tier.
  - OpenRouter.
  - Alpha Vantage.
  - Vercel.
  - Render.

Do not activate an Alpaca Live account for this MVP.

## Environment setup

1. Copy `.env.example` into the environment files selected by each app during scaffolding.
2. Fill values locally; never commit them.
3. Keep browser-exposed values limited to:

   - `NEXT_PUBLIC_SUPABASE_URL`.
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
   - Public app/API URLs.

4. Keep Alpaca, Gemini, OpenRouter, Alpha Vantage, Supabase secret, and database credentials server-side.
5. Ensure:

```text
TRADING_MODE=paper
ALPACA_PAPER=true
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets
```

The API must refuse startup for a Live host or non-paper mode.

Read [Security and Secrets](docs/SECURITY_AND_SECRETS.md) before configuring keys. Do not paste credentials into an AI chat, screenshot, issue, commit, or README.

## Local development

Exact commands will be added after the scaffold phase selects and pins the workspace tooling. The required end state is:

```text
web: http://localhost:3000
api: http://localhost:8000
api health: http://localhost:8000/health
```

README commands must be verified on Windows PowerShell because that is the primary development environment, while remaining portable to CI/Linux.

## Alpaca integrations

### Runtime API

The application uses `alpaca-py` with Paper credentials for account, assets, calendar, market data, news, positions, and order management.

### Trading MCP

The official Alpaca Trading MCP Paper connection is required for the hackathon demonstration and agent/operator workflows. Its setup and sanitized verification will be documented during the paper-execution phase.

### CLI

The Alpaca CLI is used for reproducible Paper account, asset, and order smoke tests. Never show the secret in terminal recordings or committed output.

These are complementary surfaces: the Trading API is the application runtime; MCP and CLI demonstrate agent connectivity and operational control.

## Data-provider budget

Alpha Vantage is limited to 25 free calls per day. The application must:

- Use it only for estimates and revisions.
- Persist a daily counter.
- Cache by symbol/period/provider timestamp.
- Prefer SEC for statements and Alpaca for prices/news.
- Stop before exceeding the budget.
- Never retry quota errors in a tight loop.

OpenRouter free requests are also scarce. Gemini is primary; OpenRouter is fallback-only, with a fixed model rather than the random free router.

## Testing and verification

The final implementation must provide:

- Unit tests for every financial formula and boundary.
- Provider parsing/contract tests with sanitized fixtures.
- RLS and authorization tests.
- Order-state and idempotency tests.
- Explicitly gated Alpaca Paper smoke tests.
- Component tests.
- Playwright coverage for the judge flow.
- Lint, formatting, type checks, builds, and secret scanning in CI.

No test may contact a Live Alpaca endpoint.

## Deployment

### Web — Vercel

- Deploy `apps/web`.
- Store only appropriate public values as `NEXT_PUBLIC_*`.
- Configure the Render API URL and Supabase Auth redirects.

### API — Render Free

- Deploy `apps/api` as a Python web service.
- Listen on `0.0.0.0:$PORT`.
- Configure `GET /health`.
- Store all secrets in Render environment settings.
- Expect the free service to sleep; the web UI must show a friendly waking state.

### Database/Auth — Supabase

- Apply versioned migrations.
- Use explicit grants and RLS.
- Use current publishable/secret keys rather than creating new legacy-key integrations.
- Run database advisors before the final demo.

## Documentation center

- [Product specification](docs/PRODUCT_SPEC.md)
- [Trading strategy](docs/TRADING_STRATEGY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and secrets](docs/SECURITY_AND_SECRETS.md)
- [Three-day implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [UI generation prompt](docs/UI_GENERATOR_PROMPT.md)
- [Audit of the inherited `.github`](docs/GITHUB_AUDIT.md)
- [Master build prompt](.github/prompts/00-master-build.prompt.md)

## Limitations to disclose to judges

- Paper fills differ from real execution and do not model every market condition.
- Free Render instances sleep and have cold starts.
- Free AI and Alpha Vantage quotas can become unavailable.
- News can explain context but does not prove causation.
- Analyst estimates are uncertain.
- Four-year fundamental history and historical multiples do not guarantee future returns.
- The MVP is not approved for real-money operation.

## Roadmap after the equity MVP

- Validate the equity strategy with extended paper observation and reproducible backtests.
- Add sector-specific capital rules only after evidence and tests.
- Add options analysis/execution as an isolated module with its own risk model.
- Replace free sleeping infrastructure before any reliability claim.
- Add formal evaluation datasets for AI explanations and provider drift.

## License

License decision pending. Do not assume open-source redistribution terms until a license file is added.
