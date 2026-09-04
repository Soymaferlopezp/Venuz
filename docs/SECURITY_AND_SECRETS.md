# Security and Secrets

## Golden rule

Do not send credentials in chat. The fact that this is a hackathon or paper account does not make copied secrets safe. If any key is exposed in chat, screenshots, commits, logs, or recordings, revoke/rotate it.

## Secret placement

| Secret | Local | Vercel | Render | Browser |
|---|---|---|---|---|
| Supabase publishable key | web `.env.local` | allowed | optional | allowed with RLS |
| Supabase secret key | API `.env` | no | secret env | forbidden |
| Alpaca Paper key/secret | API `.env` | no | secret env | forbidden |
| Gemini key | API `.env` | no | secret env | forbidden |
| OpenRouter key | API `.env` | no | secret env | forbidden |
| Alpha Vantage key | API `.env` | no | secret env | forbidden |
| SEC User-Agent contact | API `.env` | no | env | not needed |

GitHub Actions stores `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`, and `SUPABASE_PROJECT_ID` only as encrypted repository/environment secrets for the manual hosted-migration workflow. Their values must never appear in YAML, documentation, command arguments, or logs.

## Required controls

- `.env*` ignored except `.env.example`.
- Secret scanning in CI and pre-commit where practical.
- Structured log redaction for keys, authorization, cookies, tokens, and provider payloads.
- Supabase RLS and explicit grants.
- Backend-only privileged operations.
- Paper endpoint allowlist; fail startup if `TRADING_MODE != paper` or Alpaca base URL is not the paper host.
- CORS allowlist, secure cookies, CSRF-aware mutations, input validation, request-size limits, and rate limiting.
- Idempotency keys for mutations.
- Immutable audit records with actor, request correlation, inputs hash, decision, and remote identifiers.
- Human approval records expire and must be revalidated.

## Supabase notes for 2026

- Use `sb_publishable_*` and `sb_secret_*`; legacy keys are being deprecated.
- New public tables may not be exposed to the Data API automatically. Add explicit minimum grants and RLS.
- `TO authenticated` alone is not authorization; policies need ownership or operator-role predicates.
- Do not use user-editable metadata for authorization.
- Views exposed through the API use `security_invoker`.
- Hosted Supabase is the only database runtime for development, integration, and demonstration. Developer machines do not install or run Docker, Podman, WSL, or a local Supabase stack.
- Version migrations under `supabase/migrations`; use `supabase link`, `migration list`, `db push --dry-run`, approved `db push`, and `db lint --linked --level error` in that order.
- `db reset --linked` is prohibited. Do not automate `migration repair` or `db pull`.
- pgTAP runs only in validation CI against an ephemeral runner database that has no hosted-project credentials and is always stopped afterward.

## LLM privacy and safety

- Send minimized, non-secret market/fundamental context.
- Disable OpenRouter prompt logging and training-eligible provider routing where compatible with the chosen endpoint.
- Never give the LLM raw broker credentials or a generic HTTP tool capable of reaching arbitrary Alpaca endpoints.
- Validate LLM output; treat it as untrusted text.
- Explanation failure never relaxes a trading guard.

## Incident response for exposed keys

1. Revoke/rotate the affected key immediately.
2. Remove it from files/history and deployment variables.
3. Inspect provider and application logs for use.
4. Reissue with the narrowest available access.
5. Record a sanitized incident note and prevention action.

## Public activation security decision

Public activation does not use Supabase anonymous sign-in or visitor roles. Rate limiting is secondary abuse control; the primary defense is one durable cycle per deterministic key plus atomic provider reservations and unique Paper order intent keys. Public responses contain only safe states, evidence links, freshness, provenance, and blocking reasons. They never contain provider payloads, authorization headers, broker account details, or secrets.

## Ambiguous Paper responses

Every Paper command is reserved durably before broker access and uses a stable, unique `client_order_id`. A timeout or ambiguous response never authorizes a new intent: the service looks up the same identifier, persists a pending reconciliation state when it cannot prove the outcome, and retries only reconciliation. Closing protection is replaced only after remote cancellation is confirmed. Entry execution always requires the complete deterministic preflight, including when auto-execution is enabled; the setting is disabled by default. Automated tests inject the test-only `apps/api/tests/fakes/FakeBroker` and never read Alpaca credentials or use a network order endpoint.

## Options capability and public data

The capability probe is read-only and allowlists the exact Paper host. It exposes only approval/trading levels, boolean buying-power availability, data-surface availability, feed name, timestamps, and safe reason codes—never balances, account IDs, raw responses, headers, or credentials. Level 1 is mandatory for Cash-Secured Puts. Failure blocks Options and Mixed while Stocks remains available.

Option tables have RLS enabled and no anon/authenticated grants. Backend grants are explicit; observation/evaluation/lifecycle/settlement evidence is append-only. Public API models omit broker order IDs and client order IDs. Automatic execution remains false by default and uses the same preflight, atomic reservation, stable identifier, and Paper-only broker path when enabled.