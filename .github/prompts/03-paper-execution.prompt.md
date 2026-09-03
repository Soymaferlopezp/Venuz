# Phase 3 prompt — Alpaca paper execution and approvals

Implement the paper order lifecycle exactly as specified in `docs/TRADING_STRATEGY.md`.

Deliver:

- Order preview and complete preflight revalidation.
- Regular-hours paper market entry with actual-fill-based sizing/protection.
- 10% initial stop, +2R branch, estimated-price branch, and 5% trailing transitions.
- Reconciliation for accepted, filled, partial, canceled, rejected, replaced, and stale orders.
- Independent approval queue with expiry and revalidation; pending items never block other jobs.
- Critical automatic fundamental exits and noncritical approval exits.
- Idempotency and immutable audit events for every state transition.
- Official Alpaca Trading MCP Paper setup and smoke-test documentation.
- Alpaca CLI Paper profile and sanitized smoke tests.
- Integration tests with fakes plus explicitly gated real Paper smoke tests.

Never create or document a Live credential path. Never overlap closing orders.

## Official public-cycle amendment

Implement Paper execution only as part of the single public global cycle. `Activate Venuz` joins or returns that cycle; it never creates a visitor-specific analysis or order. Cycle creation, provider reservations, state transitions, and order idempotency must survive restarts through Postgres. Tests must use broker fakes and must not submit an external Paper order.