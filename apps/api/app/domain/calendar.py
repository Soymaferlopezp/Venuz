from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum


class EarningsState(StrEnum):
    OPEN = "open"
    PRE_EARNINGS_BLOCK = "pre_earnings_block"
    POST_EARNINGS_WAIT = "post_earnings_wait"


def earnings_state(
    as_of: date,
    sessions: Sequence[date],
    previous_earnings: date | None,
    next_earnings: date | None,
) -> EarningsState:
    ordered = sorted(set(sessions))
    completed_after = (
        sum(previous_earnings < session <= as_of for session in ordered) if previous_earnings else 2
    )
    if previous_earnings is not None and as_of >= previous_earnings and completed_after < 2:
        return EarningsState.POST_EARNINGS_WAIT
    sessions_before = (
        sum(as_of < session < next_earnings for session in ordered)
        if next_earnings is not None
        else 6
    )
    if next_earnings is not None and as_of < next_earnings and sessions_before < 5:
        return EarningsState.PRE_EARNINGS_BLOCK
    return EarningsState.OPEN


def should_recalculate(
    as_of: date, sessions: Sequence[date], latest_earnings: date, frozen_report_date: date | None
) -> bool:
    completed_after = sum(latest_earnings < session <= as_of for session in set(sessions))
    return completed_after >= 2 and frozen_report_date != latest_earnings
