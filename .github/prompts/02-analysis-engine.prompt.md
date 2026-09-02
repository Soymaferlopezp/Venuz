# Phase 2 prompt — data and deterministic analysis

Read the project instructions and implement the data/analysis vertical slice without order submission.

Deliver:

- Alpaca asset, market snapshot, calendar, corporate event/earnings where available, and News clients.
- SEC Company Facts/Submissions client with compliant User-Agent, normalization, provenance, caching, and filing links.
- Alpha Vantage estimates/revisions client with a persisted hard 25/day budget.
- Deterministic universe filters, four-year criteria, traffic lights, coherent-ratio cluster/median, confidence, target-price range, quarterly freeze, and earnings-session rules.
- Persistent scan jobs and a 10–15 candidate watchlist.
- Company-thesis API returning exact inputs, calculations, source, date, exclusions, reason, and freshness.
- Comprehensive fixtures and edge-case tests.

No LLM may determine a criterion. Missing required facts produce an explicit insufficient/no-trade result.
