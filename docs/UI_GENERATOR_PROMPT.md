# Prompt for Google Stitch, Lovable, or Replit Design Generation

Use this prompt only to generate a visual starting point. Generated code is untrusted: do not provide secrets, connect Alpaca, create databases, or accept generated business logic. Export the UI and adapt it to the repository conventions.

---

Design a polished responsive web dashboard for **Venuz**, an evidence-first US-equity analysis and Alpaca Paper Trading application. This is not a crypto casino, day-trading terminal, or generic chatbot. The product should feel calm, credible, transparent, and suitable for a financial technology hackathon jury.

Technology target: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, Lucide icons, and Recharts. Generate accessible reusable components; do not generate backend logic or include secrets.

Visual direction:

- Light-first neutral canvas with optional dark mode.
- Deep navy/slate primary color, restrained emerald for positive states, amber for caution, red only for critical failures, and Alpaca-inspired warm yellow used sparingly as an accent.
- Clear typography, generous whitespace, subtle borders/shadows, 12–16px radii.
- No neon, no flashing prices, no confetti, no glassmorphism overload, and no promises of profit.
- Persistent visible badge: “PAPER TRADING — NO REAL MONEY”.
- Every financial value includes source/freshness affordances.

Create these responsive screens and states:

1. **Judge overview / landing:** one-sentence value proposition; architecture/integration badges for Alpaca API, MCP, CLI, SEC, Supabase, Gemini, OpenRouter, Alpha Vantage; “Explore demo” CTA; safety explanation.
2. **Dashboard:** portfolio equity, 20% minimum cash gauge, invested percentage, daily paper P/L clearly labeled simulated, sector exposure, open positions, pending approvals, next earnings restrictions, recent audit events, and integration health.
3. **Screener/watchlist:** 10–15 candidates with ticker, company, sector, market cap, dollar liquidity, overall traffic light, valuation status, target range, current price, earnings window, evidence freshness, and action. Provide filters and mobile cards.
4. **Company thesis:** four-year revenue/net-income/net-margin/FCF/shareholders-equity trends; Debt/Equity; estimate-revision signals; seven criterion cards with exact formula, result, source and green/yellow/red reason; P/E and P/FCF historical observation chart with included/excluded points; frozen quarterly floor/ceiling; news/evidence timeline; AI explanation panel explicitly labeled “Explanation, not execution authority”.
5. **Order preview:** paper-only banner; market order; proposed allocation; expected cash after trade; sector exposure; actual preflight checklist; initial 10% stop; +2R objective; two trailing-stop branches; validation results; submit or request-approval actions.
6. **Approval queue:** independent cards/rows that can be approved/rejected individually; show why approval was requested, expiration, current revalidation state, evidence, and no global blocking overlay.
7. **Portfolio:** positions with allocation, sector, entry/fill, current price, R multiple, frozen target range, active stop/trailing state, next earnings, fundamental health, and lifecycle details.
8. **Orders/audit:** timeline from scan through criterion results, approval, Alpaca submission, fills, stop replacement, trailing activation, and exit; include correlation IDs and expandable sanitized provider records.
9. **Integrations/settings:** health and quota cards with only redacted key state; never show secret inputs after saving; indicate Gemini primary, OpenRouter fallback, Alpha Vantage 25/day budget, Alpaca Paper, SEC, Supabase, Vercel, and Render cold-start note.

Required component states: loading skeleton, empty, stale-data warning, provider rate-limit, Render waking/cold start, market closed, earnings blackout, insufficient evidence, no-trade, pending approval, order rejected, partial fill, offline and recovered.

Accessibility: WCAG-aware contrast, keyboard navigation, visible focus, semantic tables with mobile alternatives, chart summaries, no color-only status communication, reduced-motion support.

Return a coherent design system and all screens with realistic but obviously simulated data. Do not implement trading calculations; use placeholders indicating that values come from the deterministic backend.

---
