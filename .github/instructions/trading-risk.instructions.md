---
applyTo: "apps/api/**/*.{py,json,yaml,yml}"
---

# Trading and risk invariants

- Paper trading only.
- Universe: US-listed, market cap >= USD 10B, average daily dollar volume >= USD 20M, profitable; exclude banks, insurers, REITs, penny stocks, crypto, and unsupported/untradable assets.
- Watchlist: 10–15 candidates. Portfolio: at most 80% invested, 10% maximum per position, 20% sector cap, two companies per sector.
- All fundamental criteria must be green or yellow; any red blocks entry. Valuation must be green to submit automatically.
- Block entries for five US trading sessions before earnings and wait two completed sessions after earnings before recalculation.
- Freeze the P/E and P/FCF target-price range for the quarter after recalculation.
- Entry uses a regular-hours market order only after spread, drift, liquidity, cash, buying power, exposure, duplicate, and stale-data guards.
- Initial stop is 10% below actual fill. Initial reward target is +2R (+20% when risk is 10%).
- At +2R, keep the full position and replace the protective stop with a 5% trailing stop.
- If fair price is reached before +2R: stop at 5% below fair price; at 5% above fair price, move stop to fair price and activate 5% trailing.
- Critical fundamental red conditions exit automatically. Other red deterioration creates human approval and does not block unrelated work.
- Never maintain overlapping closing orders. Cancel/confirm before replacing stop orders.
- If any invariant cannot be proven, return `NO_TRADE` with reasons.
