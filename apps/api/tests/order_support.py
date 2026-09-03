from app.domain.paper_execution import (
    PREFLIGHT_GUARD_CODES,
    GuardResult,
    PreflightDecision,
)

APPROVED_PREFLIGHT = PreflightDecision(
    eligible=True,
    guards=tuple(
        GuardResult(code=code, passed=True, reason="passed") for code in PREFLIGHT_GUARD_CODES
    ),
)
