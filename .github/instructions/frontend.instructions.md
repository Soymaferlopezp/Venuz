---
applyTo: "apps/web/**/*.{ts,tsx,css}"
---

# Frontend instructions

- Use Next.js App Router and the default Node.js runtime. In Next.js 16+, use `proxy.ts`, not `middleware.ts`.
- Prefer Server Components for reads. Use Client Components only for interaction, charts, streaming state, or browser APIs.
- Keep Alpaca, Supabase secret, Gemini, OpenRouter, SEC contact, and Alpha Vantage credentials out of the browser bundle.
- The browser talks only to authenticated web/server boundaries and the FastAPI service; it never calls Alpaca trading endpoints directly.
- Use typed API contracts generated from FastAPI OpenAPI or a shared schema process; do not duplicate DTO shapes manually.
- Use shadcn/ui primitives, Tailwind tokens, accessible semantic HTML, keyboard support, visible focus, loading, empty, stale, and error states.
- The visual language is calm, evidence-first, and professional. Avoid casino aesthetics, flashing tickers, neon gradients, and profit-celebration animations.
- Show timestamps, data freshness, source, confidence, and why a criterion is green/yellow/red.
- Destructive actions and paper orders require explicit, understandable states; pending approvals are individually actionable and nonblocking.
- Never label simulated returns as real performance. Always display a persistent `PAPER TRADING` indicator.
- Add unit/component tests and Playwright coverage for critical flows.
