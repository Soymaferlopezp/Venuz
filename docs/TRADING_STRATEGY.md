# Deterministic Equity Strategy

Status: approved product rule set for the MVP. Changes require an explicit decision recorded in the repository.

## 1. Scope

The MVP analyzes US equities in Stocks mode and may paper-trade one-leg Cash-Secured Puts in Options or Mixed mode. Calls, naked puts, spreads, straddles, multileg strategies, crypto, live trading, banks, insurers, REITs, penny stocks, and companies without positive earnings are excluded.

## 2. Universe and portfolio construction

### Broad universe

Start from the 10–20 largest eligible companies by market capitalization in each prioritized sector:

- Technology.
- Health care.
- Consumer staples/defensive consumption.
- Consumer discretionary/cyclical consumption.
- Energy.
- Automotive.
- Non-bank financial services/fintech.

Eligibility filters:

- US-listed and tradable through Alpaca.
- Market capitalization of at least USD 10 billion.
- Average daily dollar volume of at least USD 20 million.
- Positive most-recent net income.
- Not a bank, insurer, REIT, penny stock, crypto asset, or unsupported instrument.

The screening process produces a 10–15 company watchlist. The watchlist is not the portfolio.

### Portfolio limits

- Maximum position: 10% of current portfolio equity.
- Minimum cash: 20%.
- Maximum invested: 80%.
- Maximum sector exposure: 20%.
- Maximum companies per sector: 2.
- With full-size positions, the portfolio can hold at most 8 positions.
- If there are fewer eligible opportunities, leave the unused allocation in cash.

## 3. Fundamental criteria

Evaluate four fiscal years. Quarterly comparisons use year-over-year matching quarters to reduce seasonality distortion.

### 3.1 Revenue growth

- Compare total revenue over the last four fiscal years.
- Require positive growth from the first to the latest period.
- Prefer at least 3 positive year-to-year comparisons out of the latest 4 available comparisons.
- A single explainable decline followed by recovery is yellow, not an automatic rejection.

### 3.2 Net income and net margin

- Latest net income must be positive.
- Net income should show a growing overall trend.
- Net margin must be positive and preferably growing or stable.
- Separate revenue-driven growth from actual margin quality.

### 3.3 Free cash flow

Use `free cash flow = operating cash flow - capital expenditures`.

- FCF must be positive in at least 3 of the latest 4 fiscal years.
- Latest fiscal-year FCF must be positive.
- Prefer a stable or growing overall trend.
- Latest negative FCF is critical red.

### 3.4 Shareholders' equity

Use `shareholders' equity = total assets - total liabilities`.

- Latest equity must be positive.
- Prefer a growing four-year trend.
- One isolated decline is yellow when later recovery/evidence supports it.
- Negative latest equity is critical red.

### 3.5 Debt

- Use total-debt-to-shareholders-equity where both values are valid.
- Require Debt/Equity < 1 for the MVP universe.
- Banks and insurers are excluded because their capital structures require sector-specific rules.

### 3.6 Forward estimates

Use both signals:

1. Current consensus EPS estimate is higher than the previous consensus estimate.
2. Expected EPS is higher than the comparable prior-year period.

Alpha Vantage is the scarce complementary source. Cache estimates and revisions; do not spend its daily quota on prices or statements available elsewhere.

### 3.7 Self-relative valuation

Compare each company only with itself using:

- Price/Earnings (`P/E`).
- Price/Free Cash Flow (`P/FCF`).

For each ratio:

1. Start with the previous eight completed quarterly observations; exclude the current observation.
2. Remove zero, negative, null, nonfinite, or economically invalid values.
3. Select the coherent historical cluster and explicitly record included/excluded observations and reasons.
4. Use the median of the coherent cluster.
5. Confidence: 6–8 values high; 4–5 medium; 3 low/yellow only; fewer than 3 insufficient.
6. At least 4 coherent observations are required for automatic-order eligibility.

Estimated prices are calculated independently:

`estimated_price_pe = current_price * historical_pe / current_pe`

`estimated_price_pfcf = current_price * historical_pfcf / current_pfcf`

Do not average the two estimated prices. The lower value is the range floor and the higher value is the range ceiling.

### Quarterly freeze

After an earnings report, wait two complete US trading sessions, refresh the inputs, calculate the two estimated prices, and freeze that range for the quarter. The range remains unchanged until the next report and recalculation.

## 4. Traffic lights

### Fundamental status

- Green: passes without material concern.
- Yellow: acceptable but has an isolated anomaly, reduced evidence, or explainable weakness. The explanation must cite evidence.
- Red: fails a required rule.

Entry eligibility requires every fundamental criterion to be green or yellow. Any red blocks entry.

### Valuation status

Let `floor` be the lower estimated price and `ceiling` the higher:

- Strong green: market price is at least 10% below `floor`.
- Green: market price is 5% to less than 10% below `floor`.
- Yellow: market price lies inside the estimated range or valuation confidence is low.
- Red: market price is above `ceiling`.

Only green or strong-green valuation can authorize an automatic entry.

## 5. Earnings window

- A company may be analyzed at any point in its quarter.
- Block new purchases during the 5 US trading sessions before the scheduled earnings report.
- After the report, wait 2 completed US trading sessions before recalculating and allowing a new entry.
- Use the exchange calendar, not calendar days.

## 6. Entry execution

Entry order type: market order during regular US market hours only.

Before submission, code must revalidate:

- Paper account and paper endpoint.
- Market open and regular session.
- Fresh tradable quote.
- Acceptable spread and price drift.
- Asset tradable and not restricted.
- Buying power and at least 20% post-trade cash.
- 10% position cap.
- 20% sector cap and two-company sector cap.
- No duplicate/in-flight entry.
- Earnings window.
- Fundamental and valuation status.
- Human approval status when required.

Use the actual fill, not the pre-order quote, as the entry price for risk calculations.

## 7. Risk and exits

### Initial protection

- Initial stop: 10% below actual entry fill.
- `1R` is the distance between entry and initial stop.
- Initial objective: `+2R`; with a 10% stop this is approximately +20% from entry.
- With a 10% position and 10% stop, planned portfolio risk is approximately 1%.

### If +2R occurs first

- Keep 100% of the position.
- Cancel and confirm cancellation of the existing protective closing order.
- Activate a 5% trailing stop from the highest subsequent price.

### If estimated price occurs before +2R

- Move protection to 5% below the applicable estimated price reached.
- When price reaches 5% above that estimated price, move the stop to the estimated price and activate a 5% trailing stop.
- Continue trailing the highest price until triggered.

### Fundamental deterioration

Critical red conditions exit automatically after confirming fresh authoritative data:

- Negative latest shareholders' equity.
- Negative latest free cash flow.
- Negative latest net income.
- Confirmed severe/continued deterioration that invalidates the thesis.
- Debt rule becomes invalid in a materially unsafe way.

Other red deterioration creates a human approval request. It does not block unrelated work.

### Order safety

- Alpaca trailing stops for equities are standalone orders. Do not assume they can be attached as a bracket trailing leg.
- Never maintain overlapping orders that could sell more than the held quantity.
- Reconcile fills, partial fills, canceled/rejected orders, and remote state before every transition.

## 8. Human approval

- Clear opportunities may execute automatically only when auto execution is enabled and every deterministic guard passes.
- Material uncertainty creates an individual pending approval with evidence and an expiration/revalidation requirement.
- Pending approvals never block other scans, approvals, or eligible trades.
- On approval, revalidate all price, risk, cash, exposure, freshness, market-hours, and earnings rules before submitting.
- Rejection records the reason and closes only that request.

## 9. Evidence and AI boundary

Evidence priority:

1. SEC filings and standardized SEC facts.
2. Company investor-relations releases.
3. Alpaca/Benzinga news.
4. Other explicitly approved sources.

Alpaca News may help explain anomalies, but correlation is not causation. An LLM can summarize evidence; it cannot create missing facts, change a traffic light, or submit an order on its own.

## Phase 3B Cash-Secured Put rules

Options entries are exactly one OTM put contract, Sell to Open, Market, Day, and Alpaca Paper only. Eligible contracts have 30–45 DTE and delta from -0.30 through -0.15. Quotes, spread, volume, open interest, underlying price, drift, feed, contract metadata, options buying power, cash, collateral, concentration, earnings window, duplicates, and market hours must all pass deterministic gates.

Collateral is `strike × 100`; expected premium is never counted as cash before a real fill. The IV relative signal is `current implied volatility / realized volatility`, where realized volatility uses a documented 20-session window of daily underlying returns. This signal is not IV Rank and is unavailable when either input is invalid.

Take profit buys to close at 50% of entry credit. Stop loss buys to close at or above three times entry credit, representing a loss of twice the initial credit. Remaining positions close at 21 DTE. Exit priority is critical deterioration or account risk, stop loss, 21 DTE, take profit, then noncritical rules. Assignment and expiration reconciliation are defensive lifecycle controls, not simulated events.

Options mode accepts eligible high-quality equities plus the documented liquid ETF allowlist: DIA, IWM, QQQ, and SPY. ETFs skip inapplicable corporate fundamentals but retain every liquidity, collateral, concentration, volatility, and data-quality gate. Mixed applies the additional `underlying_price <= USD 40` options gate and deterministically selects at most one winner across the best eligible Stock and Option candidate.