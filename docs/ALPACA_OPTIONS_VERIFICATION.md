# Alpaca Options Verification

This guide separates Venuz's Alpaca integration surfaces. Do not paste credentials or raw account responses into issues, logs, screenshots, or demo evidence.

## Runtime API

The FastAPI runtime imports `alpaca-py`. It reads the Paper account capability, active option contracts, option chains/snapshots, positions, and OPASN/OPTRD/OPEXP activities. The broker adapter submits only one-contract Market/Day Paper orders after deterministic preflight and durable reservation. Runtime execution is disabled by default.

## Data

Alpaca Market Data supplies underlying prices and history. Alpaca Options Data supplies chain and snapshot observations, current implied volatility, quotes, and the available OPRA or indicative feed. Venuz computes realized volatility and the IV relative signal; it never labels that value IV Rank.

## Trading MCP

The official Alpaca Trading MCP is a judge/operator verification surface, not the runtime path. Use only read-only Paper tools to inspect account capability, assets, contracts, positions, and orders. Sanitize identifiers and monetary account values before retaining evidence. Do not invoke order tools during this checkpoint.

## Alpaca CLI

CLI smoke tests are separately authorized operational checks. A safe future session may verify the selected profile is Paper and run read-only account/assets/contracts/orders commands. Capture only pass/fail capability evidence and feed names. Never print environment variables, headers, keys, secrets, account identifiers, balances, or raw provider payloads.

## Sanitized evidence checklist

- Exact host classified as `paper-api.alpaca.markets` without query strings or credentials.
- Options approved/trading levels reported as integer capability levels.
- Buying power represented only as available/unavailable in public output.
- Contracts, chain, snapshot, and feed surfaces represented as booleans or allowlisted names.
- No submission command, Paper order, hosted migration, or deployment is part of read-only verification.