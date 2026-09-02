# Master build prompt — Venuz

You are the lead engineer responsible for delivering a working three-day hackathon MVP. Work inside this repository and follow `AGENTS.md`, `.github/copilot-instructions.md`, every applicable `.github/instructions/*.instructions.md`, and all authoritative `docs/*.md` files.

## Outcome

Build, test, document, and deploy **Venuz**, a web application that screens high-quality US equities with deterministic fundamental rules, explains decisions with traceable evidence, and manages paper orders through Alpaca. The result must be understandable to judges, reproducible by developers, and safe by default.

## Required stack

- Monorepo with `apps/web`, `apps/api`, `supabase`, `docs`, and `.github`.
- Web: Next.js App Router, TypeScript, Tailwind, shadcn/ui, Recharts, Node.js 22+, Vercel.
- API: Python 3.12+, FastAPI, Pydantic v2, typed domain modules, Render Free web service.
- Data/Auth: hosted Supabase Postgres/Auth, versioned migrations, explicit grants, RLS. No local Supabase runtime on developer machines.
- Alpaca: `alpaca-py` for application runtime; Paper Trading API only; Market Data, calendar, assets, account, positions, orders and News API.
- Alpaca MCP: configure and prove the official Paper Trading MCP connection with sanitized smoke-test evidence.
- Alpaca CLI: configure paper profile and provide sanitized account/order/asset smoke-test commands and results.
- Fundamentals: SEC EDGAR Company Facts and Submissions with compliant descriptive User-Agent.
- Estimates: Alpha Vantage only for EPS/revenue estimates and revisions; enforce a hard 25-request daily budget and cache results.
- AI: Gemini Free Tier primary and a fixed free OpenRouter model fallback. Never use random `openrouter/free` for trade-related output.
- Testing: pytest, Vitest/React Testing Library, Playwright, database/RLS tests, provider contract fixtures.

## Trading strategy

Implement `docs/TRADING_STRATEGY.md` exactly. Key invariants include:

- US-listed profitable equities; >= USD 10B market cap and >= USD 20M average daily dollar volume.
- Exclude banks, insurers, REITs, penny stocks, crypto, companies without positive earnings, and untradable assets.
- Broad universe: top 10–20 eligible companies by market cap per prioritized sector; final watchlist 10–15.
- Portfolio: 10% maximum per position, 20% sector cap, two companies per sector, and 20% minimum cash.
- Evaluate four fiscal years for revenue, net income/net margin, FCF, shareholders' equity, Debt/Equity < 1, forward estimates/revisions, and self-relative P/E/P/FCF valuation.
- Historical valuation starts with eight prior completed quarters, removes invalid/outlier values using a deterministic coherent-cluster method, uses the median, records every inclusion/exclusion, requires at least four coherent values for automatic action, and grades confidence.
- Calculate independent target prices using `current price * historical ratio / current ratio`; never average P/E and P/FCF target prices.
- Recalculate two sessions after earnings and freeze the target range until the next report. Block buys five sessions before earnings.
- Fundamental entry requires no red criteria. Automatic entry also requires valuation green (5–10% below the range floor) or strong green (>=10% below floor).
- Entry: regular-hours paper market order after all deterministic preflight guards.
- Initial stop: 10% below actual fill; benefit:risk is 2:1, so +2R is approximately +20%.
- If +2R occurs first, retain 100% and activate 5% trailing.
- If estimated price occurs first, protect 5% below it; at 5% above it, move stop to estimated price and activate 5% trailing.
- Critical fundamental red exits automatically. Other red deterioration creates an independent human approval.
- Pending approval never blocks unrelated analysis or orders. Approval requires complete revalidation.

## AI boundary

- Deterministic Python code calculates facts, ratios, traffic lights, eligibility, allocation, risk, stops, and order commands.
- LLMs only summarize existing structured results and evidence.
- Validate all LLM output. If both models fail, show deterministic results without an explanation.
- Never grant the model broker credentials or an unrestricted HTTP execution tool.

## Security

- Never request secret values in chat or commit them.
- Create `.env.example`; local values go in ignored env files and deployed values in Vercel/Render secrets.
- Refuse startup if configuration points to Alpaca Live or `TRADING_MODE` is not paper.
- Redact secrets and sensitive broker metadata in logs/audit/UI.
- Use current Supabase publishable/secret keys, explicit grants, RLS, safe authorization, and database advisors.
- Add idempotency and an immutable audit trail.
- Use the hosted-first database workflow: `supabase link`, `migration list`, `db push --dry-run`, approved `db push`, then `db lint --linked --level error`. Never run `db reset --linked` or automate `migration repair`/`db pull`.
- Run pgTAP only in GitHub Actions against an ephemeral Supabase stack. `supabase start` and `db reset --local` are CI-only; developers do not install Docker, Podman, or WSL for Venuz.

## Product requirements

Implement all screens and acceptance criteria in `docs/PRODUCT_SPEC.md`. Use `docs/UI_GENERATOR_PROMPT.md` only as a visual reference. The product must always show paper/simulated labeling, data freshness, sources, reasons, and failure states.

## Execution method

1. Inspect repository and docs; do not assume missing files exist.
2. Follow `docs/IMPLEMENTATION_PLAN.md` phase order.
3. Before each phase, state files/schema/endpoints/tests and the exact exit gate.
4. Implement the smallest complete vertical slice.
5. Verify with commands and record concise evidence.
6. Update README/docs in the same change.
7. Do not proceed past a failed safety or correctness gate.

## Definition of done

- Fresh clone setup works from README and `.env.example`.
- Builds, lint, type checks, unit/integration/RLS/browser tests pass.
- Web/API deploy and communicate on free infrastructure, including cold-start UX.
- Alpaca Paper API, official MCP, and CLI have working sanitized verification.
- One complete scan-to-thesis-to-paper-order-to-protection/audit flow is demonstrated.
- No secret or live-trading path exists.
- README honestly documents architecture, strategy, sources, setup, tests, deployment, demo, limitations, and future options work.
