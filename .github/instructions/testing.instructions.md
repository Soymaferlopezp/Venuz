---
applyTo: "**/*.{test,spec}.{py,ts,tsx}"
---

# Testing instructions

- Tests must be deterministic and independent of live clocks and real external services.
- Unit-test every formula, boundary, traffic-light transition, outlier selection, earnings-session rule, allocation rule, and exit state.
- Use recorded sanitized fixtures or fakes for SEC, Alpha Vantage, Alpaca, Gemini, and OpenRouter. Never record authorization headers.
- Contract tests verify provider response parsing and provenance.
- Paper smoke tests may run only when an explicit environment flag is set and must use paper credentials/endpoints.
- Add regression cases for negative/zero EPS, negative FCF, negative equity, missing estimates, stale prices, market closed, spread spikes, partial fills, rejected/canceled orders, duplicate events, and provider rate limits.
- Critical browser flows: sign in, run scan, inspect evidence, approve/reject independently, see paper order status, and inspect audit history.
