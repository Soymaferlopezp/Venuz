from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.options import OptionEvaluation


class ExplanationProvider(Protocol):
    async def explain(self, payload: dict[str, object]) -> str: ...


class OptionExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    eligible: bool
    contract: str
    collateral: str
    decision_reasons: tuple[str, ...]
    narrative: str
    generated_by: str


class OptionExplanationService:
    """LLMs may supply narrative text but never decision fields."""

    def __init__(
        self,
        primary: ExplanationProvider | None = None,
        fallback: ExplanationProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _deterministic(evaluation: OptionEvaluation) -> OptionExplanation:
        reasons = evaluation.rejected_reasons or ("all_deterministic_options_gates_passed",)
        return OptionExplanation(
            eligible=evaluation.eligible,
            contract=evaluation.candidate.occ_symbol,
            collateral=str(evaluation.collateral),
            decision_reasons=reasons,
            narrative=(
                "This Cash-Secured Put passed every deterministic gate."
                if evaluation.eligible
                else "No trade: one or more deterministic Options gates failed."
            ),
            generated_by="deterministic_code",
        )

    async def explain(self, evaluation: OptionEvaluation) -> OptionExplanation:
        base = self._deterministic(evaluation)
        payload: dict[str, object] = {
            "eligible": base.eligible,
            "contract": base.contract,
            "collateral": base.collateral,
            "decision_reasons": base.decision_reasons,
        }
        for name, provider in (("gemini", self.primary), ("openrouter_fixed", self.fallback)):
            if provider is None:
                continue
            try:
                narrative = await provider.explain(payload)
            except Exception:
                continue
            if narrative.strip():
                return base.model_copy(
                    update={"narrative": narrative.strip(), "generated_by": name}
                )
        return base
