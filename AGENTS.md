# Venuz

## Mission

Build a hackathon-ready web application that screens high-quality US equities with a deterministic fundamental strategy, explains every decision with evidence, and executes orders only in Alpaca Paper Trading.

## Source of truth

Read these documents before changing code:

1. `docs/TRADING_STRATEGY.md` — immutable business and risk rules.
2. `docs/PRODUCT_SPEC.md` — product scope and acceptance criteria.
3. `docs/ARCHITECTURE.md` — boundaries, integrations, and data ownership.
4. `docs/SECURITY_AND_SECRETS.md` — mandatory security controls.
5. `docs/IMPLEMENTATION_PLAN.md` — delivery order and verification gates.

If documents conflict, security and paper-trading restrictions win. Never silently reinterpret a trading rule; document the conflict and stop the affected operation.

## Non-negotiable constraints

- Paper trading only. Never add or use Alpaca Live credentials or endpoints.
- Deterministic code owns screening, valuation, portfolio limits, risk, approvals, and order eligibility. LLMs may explain and summarize; they never bypass code rules.
- Never commit secrets. Use `.env.example` for names only.
- Never print secrets, full authorization headers, or sensitive account data in logs.
- Keep at least 20% cash, cap positions at 10%, sectors at 20%, and two companies per sector.
- A pending human approval must not block unrelated analyses or eligible orders.
- Every recommendation and order transition must be auditable with inputs, rule results, timestamps, evidence links, and provider provenance.
- Do not use TradingView, Groq, Ollama, Koyeb, REITs, insurers, banks, unprofitable companies, penny stocks, crypto, or live trading.

## Approved stack

- Web: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, Recharts, Node.js 22+, deployed on Vercel.
- API/agent: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x/Alembic or Supabase REST where appropriate, deployed as a Render Free web service.
- Database/Auth: hosted Supabase Postgres and Supabase Auth with explicit grants and RLS. No local Supabase runtime is used on developer machines.
- Trading/data: `alpaca-py`, Alpaca Paper Trading API, Alpaca Market Data and News API.
- Required Alpaca tooling: official Trading MCP integration and Alpaca CLI smoke tests, documented separately from the runtime API path.
- Fundamentals: SEC EDGAR Company Facts/Submissions; Alpha Vantage only for analyst estimates and revisions, aggressively cached.
- AI: Gemini Free Tier primary; OpenRouter fixed free model fallback. Never use the random `openrouter/free` router for trade-related explanations.
- Testing: pytest for Python, Vitest/React Testing Library for web units, Playwright for critical browser flows.

## Engineering workflow

1. Inspect current files and the relevant docs.
2. State the smallest implementation slice and acceptance tests.
3. Implement without unrelated refactors.
4. Add or update tests with the behavior.
5. Run formatting, type checks, tests, and builds relevant to the slice.
6. Update README/docs whenever setup, behavior, schema, variables, or deployment changes.
7. Report evidence of verification and any remaining risk.

## Architecture boundaries

- `apps/web`: presentation and authenticated user interaction. It must not contain trading secrets or trading-rule calculations.
- `apps/api`: integrations, deterministic domain engine, orchestration, approvals, and order lifecycle.
- `supabase/migrations`: versioned schema, grants, RLS, indexes, and database tests.
- `docs`: decisions and operating instructions.
- `.github`: agent instructions, prompts, templates, and CI.

## Supabase hosted-first workflow

- Hosted Supabase is the database runtime for development, integration, and demonstration.
- Keep every schema change versioned in `supabase/migrations`.
- Link the intended remote project with `supabase link`, inspect it with `supabase migration list`, preview with `supabase db push --dry-run`, apply only after explicit review with `supabase db push`, and validate with `supabase db lint --linked --level error`.
- `supabase db reset --linked` is prohibited. Do not automate `migration repair` or `db pull`.
- Developer machines do not install or use Docker, Podman, or WSL for this repository. `supabase start` and `supabase db reset --local` are CI-only commands.
- pgTAP runs only against the ephemeral Supabase stack created inside GitHub Actions; CI must never point pgTAP at the shared hosted project.

## Safety behavior

- Default to no trade when required data is missing, stale, contradictory, or invalid.
- Market orders are permitted only during regular US market hours after liquidity, spread, price-drift, buying-power, cash, position, sector, earnings-window, and duplicate-order checks.
- Stops and trailing stops must be reconciled against Alpaca order state. Avoid overlapping closing orders.
- Critical red fundamental deterioration exits automatically; noncritical red deterioration creates a nonblocking human approval.
- All monetary calculations use `Decimal`, never binary floating point.
- All timestamps are stored in UTC and displayed with an explicit timezone.

## Repository hygiene

The inherited SaludPlus/Laravel instructions and plans were removed before the initial commit. Do not reintroduce unrelated medical-domain, Laravel, Blade, Alpine, or Metronic conventions into this repository.
