# Phase 4 prompt — judge-ready web experience

Implement the screens in `docs/PRODUCT_SPEC.md` using the design direction in `docs/UI_GENERATOR_PROMPT.md`.

Requirements:

- Persistent paper-trading indicator.
- Dashboard, screener, company thesis, order preview, approvals, portfolio, orders/audit, and integrations/settings.
- Exact formulas, sources, dates, confidence, included/excluded ratio observations, frozen range, earnings windows, and clear no-trade reasons.
- Nonblocking approvals and revalidation feedback.
- Loading, empty, stale, provider-limit, market-closed, blackout, partial-fill, rejection, offline, and Render-cold-start states.
- Accessible responsive components, keyboard operation, non-color status cues, and chart text/table alternatives.
- Typed API contracts and no secret-bearing browser calls.
- Component and Playwright tests for the complete demo flow.

Do not generate generic trading-dashboard visuals or invent financial results.

## Public MVP amendment

Replace sign-in-first and role-based visitor proposals with a public landing page and one **Activate Venuz** button. Display Exploring, Analyzing, and Paper Trading as stages of the same global cycle. Provide honest quota/provider/market/data blocking states plus links to the last real analysis, retry, repository, and setup instructions. Never display invented results.