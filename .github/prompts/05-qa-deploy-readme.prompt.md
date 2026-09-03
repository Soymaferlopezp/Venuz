# Phase 5 prompt — QA, deployment, and README

Complete the product without expanding scope.

Deliver:

- Full lint, formatting, type, unit, integration, RLS, contract, build, and Playwright verification.
- Security checks for secrets, CORS, auth, RLS, input validation, paper-only host, idempotency, log redaction, and LLM boundaries.
- Vercel web deployment and Render Free API deployment with `0.0.0.0:$PORT`, `/health`, CORS, cold-start UX, and platform secrets.
- Supabase migrations/advisors and redirect configuration.
- Sanitized Alpaca API/MCP/CLI evidence.
- README finalized for judges and developers: value proposition, demo, screenshots placeholders, architecture, deterministic strategy, integrations, setup, variables, tests, deployment, security, limitations, troubleshooting, and roadmap.
- A concise demo script that works even if a free provider is rate-limited by using clearly labeled deterministic fixtures.

Do not claim production readiness, profitability, real performance, or 24/7 uptime.

## Public-cycle QA amendment

Verify 100 concurrent activations converge on one durable cycle, retries and restarts cannot duplicate a Paper order, quotas are reserved atomically, and public DTOs are sanitized. The English README must explain cloning, personal credentials, local execution, and the distinction between stored real, cached, blocked, and Paper-submitted results.