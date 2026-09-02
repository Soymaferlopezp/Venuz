# Product Specification

## Product statement

**Venuz** is an evidence-first web application that discovers high-quality US equities, applies a transparent fundamental valuation strategy, manages a paper portfolio, and demonstrates safe agent-assisted trading through Alpaca.

## Hackathon story

The differentiator is not a chatbot that happens to place orders. It is a controlled trading system where:

- Alpaca supplies market data, news, account state, paper execution, MCP tools, and CLI operations.
- SEC data grounds company fundamentals.
- Alpha Vantage adds scarce analyst-estimate signals.
- Deterministic rules own every financial calculation and risk decision.
- AI explains the evidence and helps the operator understand decisions.
- Every action is observable, reversible where possible, and auditable.

## Personas

- Operator: configures paper mode, runs scans, reviews evidence, manages approvals, and observes positions.
- Judge/demo viewer: understands the strategy, integrations, safeguards, and a complete paper-trade lifecycle.

## MVP user journeys

### 1. Integration readiness

The operator sees status for Alpaca Paper, SEC, Alpha Vantage budget, Gemini, OpenRouter fallback, Supabase, and market calendar without revealing credentials.

### 2. Build the watchlist

The operator starts a scan. The system constructs the eligible universe, applies market-cap/liquidity/exclusion filters, evaluates fundamentals, and ranks 10–15 candidates with freshness and provenance.

### 3. Inspect a company thesis

The company page shows:

- Four-year statements and trends.
- Seven criteria with green/yellow/red status and exact calculation.
- Historical P/E and P/FCF observations, included/excluded cluster values, confidence, and frozen quarterly range.
- Earnings restriction window.
- Evidence/news timeline.
- AI explanation clearly labeled as explanation, not source-of-truth calculation.

### 4. Create or approve a paper order

An eligible green valuation can produce an order preview. If uncertainty requires approval, it enters an independent queue. Approval always triggers revalidation. Successful submission shows remote Alpaca status and protective-stop state.

### 5. Monitor portfolio and exits

The dashboard shows cash reserve, sector exposure, position risk, fair-price range, current R multiple, stop mode, trailing state, and fundamental deterioration alerts.

### 6. Audit everything

The audit page reconstructs a decision from provider inputs through criteria, approval, order submission, fills, stop transitions, and exit.

## Required screens

1. Public/intro landing or judge overview.
2. Sign-in.
3. Dashboard.
4. Screener/watchlist.
5. Company detail/thesis.
6. Opportunity/order preview.
7. Approval queue.
8. Portfolio/positions.
9. Orders and lifecycle detail.
10. Audit/evidence timeline.
11. Integration/settings status with redacted secrets.

## Functional requirements

- Paper-mode banner on every authenticated screen.
- Manual `Run scan` capability so Render sleep or scheduler delays do not block the demo.
- Background-capable scan jobs represented persistently with progress and failure details.
- Nonblocking approval queue.
- Cached, rate-budgeted provider access.
- Freshness labels and source provenance.
- Idempotent order and transition handling.
- Responsive desktop/tablet/mobile UI.
- Accessible navigation and data visualization alternatives.

## Out of scope

- Live trading.
- Options execution in this first MVP.
- Crypto.
- TradingView.
- Backtest claims presented as guaranteed performance.
- Social trading, deposits, withdrawals, broker onboarding, or multi-broker support.
- A fully autonomous production-grade 24/7 service on free infrastructure.

## Demo acceptance criteria

- A fresh clone can be configured from `.env.example` without reading source code for secret names.
- CI passes lint, type check, unit tests, and builds.
- App visibly operates in Alpaca Paper mode.
- One scan can produce a watchlist and at least one detailed thesis from fixtures or current provider data.
- Every criterion shows formula, data, source, date, and status.
- Order preview proves all portfolio/risk guards.
- Paper order can be submitted and its state reconciled when credentials are available.
- Approval requests do not block unrelated work.
- README explains setup, architecture, strategy, integrations, limitations, and demonstration steps.
