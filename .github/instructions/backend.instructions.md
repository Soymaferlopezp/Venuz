---
applyTo: "apps/api/**/*.py"
---

# Backend instructions

- Use Python 3.12+, FastAPI, Pydantic v2, typed functions, `Decimal` for money/ratios, UTC storage, and structured logging.
- Organize by domain boundaries: `integrations`, `fundamentals`, `valuation`, `portfolio`, `risk`, `orders`, `approvals`, `agents`, and `audit`.
- Keep pure deterministic calculations separate from network clients and persistence.
- The LLM may summarize evidence and produce user-facing explanations. It cannot calculate authoritative values, alter thresholds, call Alpaca directly, or approve orders.
- Every external client must set explicit timeouts, bounded retries, backoff, rate-limit handling, cache keys, and provenance metadata.
- SEC facts are primary for statements. Alpha Vantage is limited to estimates/revisions and a hard daily budget. Alpaca supplies tradable assets, prices, calendar, account, positions, orders, and news.
- Enforce idempotency for scans, approvals, order submissions, stop replacement, and exit transitions.
- Use a state machine for order lifecycle. Reconcile remote Alpaca state before mutations.
- Expose `/health` as a lightweight Render health check; listen on `0.0.0.0:$PORT`.
- Never log secrets or complete broker payloads containing sensitive fields.
- Add unit, integration-with-fakes, and paper smoke tests. Live endpoints are forbidden in every test.
