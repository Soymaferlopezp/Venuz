# Repository instructions

This repository builds a deterministic US-equity fundamental trading agent for Alpaca Paper Trading. Read `AGENTS.md` and all files under `docs/` before implementation.

## Absolute rules

- Paper only: `https://paper-api.alpaca.markets`. Never create live-trading setup.
- Never commit, request in chat, display, or log real secret values.
- LLM output cannot authorize a trade. Python domain rules make every eligibility and risk decision.
- Preserve the strategy in `docs/TRADING_STRATEGY.md` exactly.
- Use current official documentation for Alpaca, Supabase, Gemini, OpenRouter, SEC, Vercel, and Render.
- Pin dependencies and commit lockfiles.
- Every integration needs timeout, bounded retry with jitter, rate-limit handling, caching, provenance, and a failure-safe result.
- Missing or stale required data means `NO_TRADE`, not an inferred value.
- Update README and docs in the same change as behavior, schema, environment, or deployment changes.

## Stack

- `apps/web`: Next.js App Router + TypeScript + Tailwind + shadcn/ui + Recharts, Node 22+, Vercel.
- `apps/api`: Python 3.12 + FastAPI + Pydantic v2, Render web service.
- `supabase`: Postgres, Auth, explicit grants, RLS, migrations.
- Alpaca Paper API/Market Data/News through `alpaca-py`; official Alpaca MCP and CLI must have documented smoke tests.
- SEC EDGAR for financial statements; Alpha Vantage only for estimates; Gemini primary and fixed OpenRouter model fallback.

## Legacy exclusion

Ignore `.github/instrucctions/**` and the historical medical plans in `.github/plans/**`. They belong to SaludPlus/Laravel and are not valid project instructions.
