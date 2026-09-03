from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from app.domain.models import Eligibility, UniverseAsset, UniverseDecision

MIN_MARKET_CAP = Decimal("10000000000")
MIN_DOLLAR_VOLUME = Decimal("20000000")
PENNY_STOCK_MAX_PRICE = Decimal("5")
EXCLUDED_INDUSTRIES = {"bank", "insurer", "reit"}


def evaluate_asset(asset: UniverseAsset) -> UniverseDecision:
    reasons: list[str] = []
    if not asset.us_listed:
        reasons.append("not_us_listed")
    if not asset.tradable:
        reasons.append("not_tradable")
    if asset.instrument_type != "equity":
        reasons.append("unsupported_instrument")
    if asset.market_cap is None or asset.market_cap < MIN_MARKET_CAP:
        reasons.append("market_cap_below_10b_or_missing")
    if (
        asset.average_daily_dollar_volume is None
        or asset.average_daily_dollar_volume < MIN_DOLLAR_VOLUME
    ):
        reasons.append("dollar_volume_below_20m_or_missing")
    if asset.latest_net_income is None or asset.latest_net_income <= 0:
        reasons.append("not_profitable_or_missing")
    if asset.current_price is None or asset.current_price <= PENNY_STOCK_MAX_PRICE:
        reasons.append("penny_stock_or_missing_price")
    if (
        asset.excluded_industry is not None
        and asset.excluded_industry.lower() in EXCLUDED_INDUSTRIES
    ):
        reasons.append(f"excluded_{asset.excluded_industry.lower()}")
    return UniverseDecision(
        asset=asset,
        eligibility=Eligibility.NO_TRADE if reasons else Eligibility.ELIGIBLE,
        reasons=tuple(reasons),
    )


def build_watchlist(
    assets: Sequence[UniverseAsset], size: int = 15
) -> tuple[UniverseDecision, ...]:
    if not 10 <= size <= 15:
        raise ValueError("watchlist size must be between 10 and 15")
    per_sector: dict[str, list[UniverseDecision]] = defaultdict(list)
    for asset in assets:
        decision = evaluate_asset(asset)
        if decision.eligibility == Eligibility.ELIGIBLE:
            per_sector[asset.company.sector.slug].append(decision)
    broad: list[UniverseDecision] = []
    for decisions in per_sector.values():
        decisions.sort(key=lambda item: item.asset.market_cap or Decimal(0), reverse=True)
        broad.extend(decisions[:20])
    broad.sort(
        key=lambda item: (
            not item.asset.company.sector.prioritized,
            -(item.asset.market_cap or Decimal(0)),
            item.asset.company.ticker,
        )
    )
    return tuple(broad[:size])
