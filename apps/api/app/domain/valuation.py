from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from statistics import median

from app.domain.models import (
    Confidence,
    CriterionResult,
    RatioCluster,
    RatioObservation,
    TrafficLight,
    ValuationRange,
    ValuationStatus,
)

COHERENCE_MAX_RATIO = Decimal("1.50")


def _confidence(count: int) -> Confidence:
    if 6 <= count <= 8:
        return Confidence.HIGH
    if 4 <= count <= 5:
        return Confidence.MEDIUM
    if count == 3:
        return Confidence.LOW
    return Confidence.INSUFFICIENT


def select_coherent_cluster(
    ratio_type: str, observations: Sequence[RatioObservation]
) -> RatioCluster:
    prior = sorted(observations, key=lambda item: item.period_end, reverse=True)[:8]
    valid = sorted(
        (
            item
            for item in prior
            if item.value is not None and item.value.is_finite() and item.value > 0
        ),
        key=lambda item: (item.value, item.period_end),
    )
    best: list[RatioObservation] = []
    for start in range(len(valid)):
        for end in range(start, len(valid)):
            candidate = valid[start : end + 1]
            low = candidate[0].value
            high = candidate[-1].value
            assert low is not None and high is not None
            if high / low <= COHERENCE_MAX_RATIO and len(candidate) > len(best):
                best = candidate
    included_keys = {(item.period_end, item.value) for item in best}
    audited: list[RatioObservation] = []
    for item in prior:
        if item.value is None:
            reason = "missing"
        elif not item.value.is_finite():
            reason = "nonfinite"
        elif item.value <= 0:
            reason = "nonpositive"
        elif (item.period_end, item.value) not in included_keys:
            reason = "outside deterministic 1.50x coherent cluster"
        else:
            reason = "included in largest coherent cluster"
        audited.append(
            item.model_copy(update={"included": reason.startswith("included"), "reason": reason})
        )
    values = [item.value for item in best if item.value is not None]
    cluster_median = Decimal(str(median(values))) if values else None
    return RatioCluster(
        ratio_type=ratio_type,
        observations=tuple(sorted(audited, key=lambda item: item.period_end)),
        median=cluster_median,
        confidence=_confidence(len(values)),
    )


def _weakest_confidence(left: Confidence, right: Confidence) -> Confidence:
    order = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]
    return min((left, right), key=order.index)


def build_valuation_range(
    current_price: Decimal,
    current_pe: Decimal | None,
    current_pfcf: Decimal | None,
    pe_cluster: RatioCluster,
    pfcf_cluster: RatioCluster,
) -> ValuationRange:
    confidence = _weakest_confidence(pe_cluster.confidence, pfcf_cluster.confidence)
    valid = (
        current_price > 0
        and current_pe is not None
        and current_pe > 0
        and current_pfcf is not None
        and current_pfcf > 0
        and pe_cluster.median is not None
        and pfcf_cluster.median is not None
    )
    if not valid:
        return ValuationRange(
            current_price=current_price,
            estimated_price_pe=None,
            estimated_price_pfcf=None,
            floor=None,
            ceiling=None,
            green_price=None,
            strong_green_price=None,
            status=ValuationStatus.INSUFFICIENT,
            confidence=Confidence.INSUFFICIENT,
            automatic_action_eligible=False,
        )
    assert current_pe is not None and current_pfcf is not None
    assert pe_cluster.median is not None and pfcf_cluster.median is not None
    price_pe = current_price * pe_cluster.median / current_pe
    price_pfcf = current_price * pfcf_cluster.median / current_pfcf
    floor = min(price_pe, price_pfcf)
    ceiling = max(price_pe, price_pfcf)
    green_price = floor * Decimal("0.95")
    strong_green_price = floor * Decimal("0.90")
    if current_price > ceiling:
        status = ValuationStatus.RED
    elif confidence in (Confidence.LOW, Confidence.INSUFFICIENT):
        status = ValuationStatus.YELLOW
    elif current_price <= strong_green_price:
        status = ValuationStatus.STRONG_GREEN
    elif current_price <= green_price:
        status = ValuationStatus.GREEN
    else:
        status = ValuationStatus.YELLOW
    automatic = (
        status in (ValuationStatus.GREEN, ValuationStatus.STRONG_GREEN)
        and pe_cluster.confidence in (Confidence.MEDIUM, Confidence.HIGH)
        and pfcf_cluster.confidence in (Confidence.MEDIUM, Confidence.HIGH)
    )
    return ValuationRange(
        current_price=current_price,
        estimated_price_pe=price_pe,
        estimated_price_pfcf=price_pfcf,
        floor=floor,
        ceiling=ceiling,
        green_price=green_price,
        strong_green_price=strong_green_price,
        status=status,
        confidence=confidence,
        automatic_action_eligible=automatic,
    )


def valuation_criterion(value: ValuationRange) -> CriterionResult:
    if value.status == ValuationStatus.INSUFFICIENT:
        status = TrafficLight.INSUFFICIENT
    elif value.status == ValuationStatus.RED:
        status = TrafficLight.RED
    elif value.status == ValuationStatus.YELLOW:
        status = TrafficLight.YELLOW
    else:
        status = TrafficLight.GREEN
    return CriterionResult(
        criterion="self_relative_valuation",
        status=status,
        formula=(
            "price x historical median / current ratio, calculated separately for P/E and P/FCF"
        ),
        reason=f"Valuation status is {value.status.value}",
        values={
            "estimated_price_pe": value.estimated_price_pe,
            "estimated_price_pfcf": value.estimated_price_pfcf,
            "floor": value.floor,
            "ceiling": value.ceiling,
        },
    )
