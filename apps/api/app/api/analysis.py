from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.core.auth import AuthenticatedUser, get_current_user
from app.domain.models import (
    CompanyThesis,
    CriterionResult,
    Evidence,
    ProviderBudget,
    ValuationRange,
)
from app.integrations.alpha_vantage import BudgetExhausted
from app.integrations.base import ProviderError
from app.repositories.analysis import AnalysisRepository
from app.services.analysis import AnalysisService
from app.services.provider_analysis import COMPANY_SPECS, ProviderAnalysisService

router = APIRouter(prefix="/v1", tags=["analysis"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
RunMode = Literal["provider", "fixture"]


class BudgetReader(Protocol):
    async def provider_budget(
        self, owner_id: str, provider: str, today: date
    ) -> ProviderBudget: ...


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: RunMode = "provider"
    fixture_mode: bool | None = None

    @property
    def selected_mode(self) -> RunMode:
        if self.fixture_mode is not None:
            return "fixture" if self.fixture_mode else "provider"
        return self.mode


class WatchlistResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: tuple[CompanyThesis, ...]


class ProviderStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    alpaca: str
    sec_edgar: str
    alpha_vantage: str
    supabase: str
    alpha_vantage_budget: ProviderBudget
    note: str


def _watchlist_rank(thesis: CompanyThesis) -> tuple[int, int, int, int, str]:
    status_penalty = {"green": 0, "yellow": 1, "insufficient": 2, "red": 3}
    valuation_penalty = {
        "strong_green": 0,
        "green": 1,
        "yellow": 2,
        "insufficient": 3,
        "red": 4,
    }
    red_or_missing = sum(
        criterion.status.value in {"red", "insufficient"} for criterion in thesis.criteria
    )
    criterion_penalty = sum(status_penalty[criterion.status.value] for criterion in thesis.criteria)
    return (
        0 if thesis.data_state.value == "fresh" else 1,
        red_or_missing,
        criterion_penalty,
        valuation_penalty[thesis.valuation.status.value],
        thesis.company.ticker,
    )


def _repository(request: Request) -> AnalysisRepository:
    return cast(AnalysisRepository, request.app.state.analysis_repository)


def _provider_service(request: Request) -> ProviderAnalysisService:
    return cast(ProviderAnalysisService, request.app.state.analysis_service)


async def _latest(request: Request, user: AuthenticatedUser, symbol: str) -> CompanyThesis:
    thesis = await _repository(request).latest_thesis(str(user.id), symbol.upper())
    if thesis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No analysis found")
    return thesis


async def _run(
    request: Request,
    user: AuthenticatedUser,
    symbol: str,
    mode: RunMode,
) -> CompanyThesis:
    repository = _repository(request)
    owner_id = str(user.id)
    now = datetime.now(UTC)
    if mode == "fixture":
        if request.app.state.settings.app_env == "production":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Fixture mode is disabled in production",
            )
        return await AnalysisService(repository).analyze_fixture(owner_id, symbol, now)
    key = f"analysis:{symbol.upper()}:{now.date().isoformat()}"
    job_id = await repository.start_job(owner_id, key, "company_analysis")
    try:
        thesis = await _provider_service(request).analyze(owner_id, symbol, now)
    except BudgetExhausted as error:
        await repository.finish_job(job_id, succeeded=False, failure_code="provider_exhausted")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"state": "provider_exhausted", "message": str(error)},
        ) from error
    except ProviderError as error:
        await repository.finish_job(job_id, succeeded=False, failure_code="provider_error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"state": "error", "message": str(error)},
        ) from error
    await repository.finish_job(job_id, succeeded=True)
    return thesis


@router.post("/analysis/{symbol}", response_model=CompanyThesis)
async def run_analysis(
    symbol: str, body: AnalysisRequest, request: Request, user: CurrentUser
) -> CompanyThesis:
    return await _run(request, user, symbol, body.selected_mode)


@router.get("/analysis/{symbol}/latest", response_model=CompanyThesis)
async def latest_analysis(symbol: str, request: Request, user: CurrentUser) -> CompanyThesis:
    return await _latest(request, user, symbol)


@router.get("/analysis/{symbol}/criteria", response_model=tuple[CriterionResult, ...])
async def analysis_criteria(
    symbol: str, request: Request, user: CurrentUser
) -> tuple[CriterionResult, ...]:
    return (await _latest(request, user, symbol)).criteria


@router.get("/analysis/{symbol}/valuation", response_model=ValuationRange)
async def analysis_valuation(symbol: str, request: Request, user: CurrentUser) -> ValuationRange:
    return (await _latest(request, user, symbol)).valuation


@router.get("/analysis/{symbol}/evidence", response_model=tuple[Evidence, ...])
async def analysis_evidence(
    symbol: str, request: Request, user: CurrentUser
) -> tuple[Evidence, ...]:
    return (await _latest(request, user, symbol)).evidence


@router.post("/watchlists/build", response_model=WatchlistResponse)
async def build_watchlist(
    request: Request,
    user: CurrentUser,
    mode: Annotated[RunMode, Query()] = "provider",
) -> WatchlistResponse:
    analyzed = [await _run(request, user, ticker, mode) for ticker in COMPANY_SPECS]
    built = tuple(sorted(analyzed, key=_watchlist_rank))
    await _repository(request).save_watchlist(str(user.id), built)
    return WatchlistResponse(items=built)


@router.get("/watchlists/latest", response_model=WatchlistResponse)
async def latest_watchlist(request: Request, user: CurrentUser) -> WatchlistResponse:
    return WatchlistResponse(items=await _repository(request).latest_watchlist(str(user.id)))


@router.get("/providers/status", response_model=ProviderStatusResponse)
async def provider_status(request: Request, user: CurrentUser) -> ProviderStatusResponse:
    store = request.app.state.provider_store
    if hasattr(store, "provider_budget"):
        budget = await cast(BudgetReader, store).provider_budget(
            str(user.id), "alpha_vantage", datetime.now(UTC).date()
        )
        database = "connected"
    else:
        budget = ProviderBudget(
            provider="alpha_vantage",
            budget_date=datetime.now(UTC).date(),
            request_count=0,
        )
        database = "test_memory"
    return ProviderStatusResponse(
        alpaca="configured_read_only",
        sec_edgar="configured_cached",
        alpha_vantage="configured_budgeted",
        supabase=database,
        alpha_vantage_budget=budget,
        note="Sanitized status. Missing or stale inputs always produce NO_TRADE.",
    )
