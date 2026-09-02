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
