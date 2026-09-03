from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.domain.models import CompanyThesis, ProviderBudget, TrafficLight
from app.integrations.alpha_vantage import BudgetExhausted
from app.integrations.base import JsonValue


class AnalysisRepository(Protocol):
    async def save_thesis(self, owner_id: str, thesis: CompanyThesis) -> None: ...
    async def latest_thesis(self, owner_id: str, symbol: str) -> CompanyThesis | None: ...
    async def frozen_thesis(
        self, owner_id: str, symbol: str, report_date: date
    ) -> CompanyThesis | None: ...
    async def save_watchlist(self, owner_id: str, theses: tuple[CompanyThesis, ...]) -> None: ...
    async def latest_watchlist(self, owner_id: str) -> tuple[CompanyThesis, ...]: ...
    async def start_job(self, owner_id: str, key: str, job_type: str) -> str: ...
    async def finish_job(
        self, job_id: str, *, succeeded: bool, failure_code: str | None = None
    ) -> None: ...


class MemoryAnalysisRepository:
    def __init__(self) -> None:
        self.theses: dict[tuple[str, str], CompanyThesis] = {}
        self.history: dict[tuple[str, str, date], CompanyThesis] = {}
        self.watchlists: dict[str, tuple[CompanyThesis, ...]] = {}
        self.jobs: dict[str, str] = {}

    async def save_thesis(self, owner_id: str, thesis: CompanyThesis) -> None:
        self.theses[(owner_id, thesis.company.ticker)] = thesis
        if thesis.valuation.report_date is not None:
            self.history[(owner_id, thesis.company.ticker, thesis.valuation.report_date)] = thesis

    async def latest_thesis(self, owner_id: str, symbol: str) -> CompanyThesis | None:
        return self.theses.get((owner_id, symbol.upper()))

    async def frozen_thesis(
        self, owner_id: str, symbol: str, report_date: date
    ) -> CompanyThesis | None:
        return self.history.get((owner_id, symbol.upper(), report_date))

    async def save_watchlist(self, owner_id: str, theses: tuple[CompanyThesis, ...]) -> None:
        self.watchlists[owner_id] = theses

    async def latest_watchlist(self, owner_id: str) -> tuple[CompanyThesis, ...]:
        return self.watchlists.get(owner_id, ())

    async def start_job(self, owner_id: str, key: str, job_type: str) -> str:
        job_id = str(uuid5(NAMESPACE_URL, f"{owner_id}:{job_type}:{key}"))
        self.jobs[job_id] = "running"
        return job_id

    async def finish_job(
        self, job_id: str, *, succeeded: bool, failure_code: str | None = None
    ) -> None:
        fallback = failure_code or "unknown"
        self.jobs[job_id] = "succeeded" if succeeded else f"failed:{fallback}"


class SupabaseRestStore:
    def __init__(self, base_url: str, secret_key: str, client: httpx.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client
        self._headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

    async def get(self, key: str, now: datetime) -> JsonValue | None:
        response = await self.client.get(
            f"{self.base_url}/rest/v1/provider_cache_entries",
            params={
                "cache_key": f"eq.{key}",
                "expires_at": f"gte.{now.astimezone(UTC).isoformat()}",
                "select": "payload",
                "limit": "1",
            },
            headers=self._headers,
            timeout=10,
        )
        response.raise_for_status()
        payload: object = response.json()
        if not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        return row.get("payload") if isinstance(row, dict) else None

    async def put(self, key: str, value: JsonValue, expires_at: datetime) -> None:
        provider = key.split(":", maxsplit=1)[0]
        symbol = value.get("symbol") if isinstance(value, dict) else None
        period_key = None
        source_as_of = None
        if isinstance(value, dict):
            period_key = value.get("lastRefreshed") or value.get("period")
            source_as_of = value.get("source_as_of") or value.get("lastRefreshed")
        response = await self.client.post(
            f"{self.base_url}/rest/v1/provider_cache_entries",
            params={"on_conflict": "cache_key"},
            headers=self._headers | {"Prefer": "resolution=merge-duplicates"},
            json={
                "cache_key": key,
                "provider": provider,
                "symbol": symbol,
                "period_key": period_key,
                "source_as_of": source_as_of,
                "payload": value,
                "expires_at": expires_at.astimezone(UTC).isoformat(),
            },
            timeout=10,
        )
        response.raise_for_status()

    async def reserve(self, owner_id: str, provider: str, budget_date: date, limit: int) -> int:
        response = await self.client.post(
            f"{self.base_url}/rest/v1/rpc/reserve_provider_budget",
            headers=self._headers,
            json={
                "p_owner_id": owner_id,
                "p_provider": provider,
                "p_budget_date": budget_date.isoformat(),
                "p_request_limit": limit,
            },
            timeout=10,
        )
        if response.status_code == 409:
            raise BudgetExhausted("Provider daily budget exhausted")
        response.raise_for_status()
        remaining = response.json()
        if not isinstance(remaining, int):
            raise RuntimeError("Invalid provider budget response")
        return remaining

    async def provider_budget(self, owner_id: str, provider: str, today: date) -> ProviderBudget:
        response = await self.client.get(
            f"{self.base_url}/rest/v1/provider_budgets",
            params={
                "owner_id": f"eq.{owner_id}",
                "provider": f"eq.{provider}",
                "budget_date": f"eq.{today.isoformat()}",
                "select": "provider,budget_date,request_limit,request_count",
            },
            headers=self._headers,
            timeout=10,
        )
        response.raise_for_status()
        rows: object = response.json()
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
            return ProviderBudget(provider=provider, budget_date=today)
        return ProviderBudget.model_validate(rows[0])


class SupabaseAnalysisRepository:
    def __init__(self, store: SupabaseRestStore) -> None:
        self.store = store

    async def _request(
        self,
        method: str,
        table: str,
        *,
        params: Mapping[str, str] | None = None,
        payload: object | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = self.store._headers
        if prefer is not None:
            headers = headers | {"Prefer": prefer}
        safe_payload = json.loads(json.dumps(payload, default=str)) if payload is not None else None
        response = await self.store.client.request(
            method,
            f"{self.store.base_url}/rest/v1/{table}",
            params=params,
            json=safe_payload,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    async def _upsert_one(
        self, table: str, payload: Mapping[str, object], conflict: str
    ) -> Mapping[str, Any]:
        rows = await self._request(
            "POST",
            table,
            params={"on_conflict": conflict},
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
            raise RuntimeError(f"Supabase {table} upsert returned no row")
        return rows[0]

    async def _ensure_owner(self, owner_id: str) -> None:
        await self._upsert_one(
            "profiles",
            {"user_id": owner_id, "display_name": "Venuz operator"},
            "user_id",
        )
        await self._upsert_one("app_roles", {"user_id": owner_id, "role": "operator"}, "user_id")

    async def _company(self, thesis: CompanyThesis) -> Mapping[str, Any]:
        sector = await self._upsert_one(
            "sectors",
            {
                "slug": thesis.company.sector.slug,
                "name": thesis.company.sector.name,
                "is_prioritized": thesis.company.sector.prioritized,
            },
            "slug",
        )
        return await self._upsert_one(
            "companies",
            {
                "sector_id": sector["id"],
                "ticker": thesis.company.ticker,
                "name": thesis.company.name,
                "exchange": thesis.company.exchange,
                "cik": thesis.company.cik,
            },
            "ticker",
        )

    @staticmethod
    def _hash(thesis: CompanyThesis) -> str:
        raw = json.dumps(thesis.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    async def save_thesis(self, owner_id: str, thesis: CompanyThesis) -> None:
        await self._ensure_owner(owner_id)
        company = await self._company(thesis)
        sec_evidence = next(
            (item for item in thesis.evidence if item.provenance.provider == "sec_edgar"),
            None,
        )
        if thesis.financial_years and sec_evidence is not None:
            financial_rows: list[dict[str, object]] = []
            for year in thesis.financial_years:
                concepts = {
                    "revenue": year.revenue,
                    "net_income": year.net_income,
                    "operating_cash_flow": year.operating_cash_flow,
                    "capital_expenditures": year.capital_expenditures,
                    "total_assets": year.total_assets,
                    "total_liabilities": year.total_liabilities,
                    "total_debt": year.total_debt,
                }
                for concept, value in concepts.items():
                    financial_rows.append(
                        {
                            "owner_id": owner_id,
                            "company_id": company["id"],
                            "provider": "sec_edgar",
                            "taxonomy": "us-gaap",
                            "concept": concept,
                            "fiscal_year": year.period.fiscal_year,
                            "fiscal_period": year.period.fiscal_period,
                            "period_end": year.period.end,
                            "unit": "USD",
                            "value": value,
                            "filed_at": year.period.filed_at,
                            "source_url": sec_evidence.provenance.source_url,
                            "source_fetched_at": sec_evidence.provenance.fetched_at,
                        }
                    )
            await self._request(
                "POST",
                "financial_facts",
                params={
                    "on_conflict": (
                        "owner_id,company_id,provider,taxonomy,concept,period_end,fiscal_period"
                    )
                },
                payload=financial_rows,
                prefer="resolution=merge-duplicates",
            )
        if thesis.forward_estimates is not None:
            estimates = thesis.forward_estimates
            await self._request(
                "POST",
                "estimate_snapshots",
                params={
                    "on_conflict": "owner_id,company_id,provider,comparable_period,source_as_of"
                },
                payload={
                    "owner_id": owner_id,
                    "company_id": company["id"],
                    "provider": "alpha_vantage",
                    "comparable_period": estimates.comparable_period,
                    "consensus_eps": estimates.consensus_eps,
                    "previous_consensus_eps": estimates.previous_consensus_eps,
                    "prior_year_eps": estimates.prior_year_eps,
                    "source_as_of": estimates.provenance.source_as_of,
                    "fetched_at": estimates.provenance.fetched_at,
                    "provenance": estimates.provenance.model_dump(mode="json"),
                },
                prefer="resolution=merge-duplicates",
            )
        if thesis.market is not None:
            market = thesis.market
            await self._request(
                "POST",
                "market_snapshots",
                params={"on_conflict": "owner_id,company_id,provider,observed_at"},
                payload={
                    "owner_id": owner_id,
                    "company_id": company["id"],
                    "provider": "alpaca",
                    "price": market.price,
                    "bid_price": market.bid,
                    "ask_price": market.ask,
                    "average_daily_dollar_volume": market.average_daily_dollar_volume,
                    "observed_at": market.observed_at,
                    "fetched_at": market.provenance.fetched_at,
                    "provenance": market.provenance.model_dump(mode="json"),
                },
                prefer="resolution=merge-duplicates",
            )
        raw = thesis.model_dump(mode="json")
        generated = thesis.generated_at.astimezone(UTC).isoformat()
        fresh_until = thesis.fresh_until or thesis.generated_at + timedelta(hours=24)
        valuation_rows = await self._request(
            "POST",
            "valuation_snapshots",
            payload={
                "owner_id": owner_id,
                "company_id": company["id"],
                "as_of": generated,
                "frozen_until_earnings_at": (
                    thesis.valuation.report_date.isoformat()
                    if thesis.valuation.report_date is not None
                    else None
                ),
                "current_price": str(thesis.valuation.current_price),
                "estimated_price_pe": thesis.valuation.estimated_price_pe,
                "estimated_price_pfcf": thesis.valuation.estimated_price_pfcf,
                "range_floor": thesis.valuation.floor,
                "range_ceiling": thesis.valuation.ceiling,
                "confidence": thesis.valuation.confidence.value,
                "status": thesis.valuation.status.value,
                "observations": {
                    "pe": thesis.pe_cluster.model_dump(mode="json"),
                    "pfcf": thesis.pfcf_cluster.model_dump(mode="json"),
                },
                "provenance": [item.provenance.model_dump(mode="json") for item in thesis.evidence],
            },
            prefer="return=representation",
        )
        valuation_id = valuation_rows[0]["id"]
        ratio_rows = [
            {
                "owner_id": owner_id,
                "valuation_snapshot_id": valuation_id,
                "ratio_type": item.ratio_type,
                "period_end": item.period_end.isoformat(),
                "value": item.value,
                "included": item.included,
                "exclusion_reason": None if item.included else item.reason,
                "source_url": item.source_url,
            }
            for cluster in (thesis.pe_cluster, thesis.pfcf_cluster)
            for item in cluster.observations
        ]
        if ratio_rows:
            await self._request("POST", "ratio_observations", payload=ratio_rows)
        key = f"analysis:{thesis.company.ticker}:{generated}"
        run = await self._upsert_one(
            "screening_runs",
            {
                "owner_id": owner_id,
                "status": "succeeded",
                "strategy_version": "phase2-v1",
                "idempotency_key": key,
                "inputs_hash": self._hash(thesis),
                "started_at": generated,
                "completed_at": generated,
            },
            "owner_id,idempotency_key",
        )
        overall = TrafficLight.GREEN
        if any(item.status == TrafficLight.RED for item in thesis.criteria):
            overall = TrafficLight.RED
        elif any(item.status == TrafficLight.INSUFFICIENT for item in thesis.criteria):
            overall = TrafficLight.INSUFFICIENT
        elif any(item.status == TrafficLight.YELLOW for item in thesis.criteria):
            overall = TrafficLight.YELLOW
        result = await self._upsert_one(
            "screening_results",
            {
                "owner_id": owner_id,
                "screening_run_id": run["id"],
                "company_id": company["id"],
                "valuation_snapshot_id": valuation_id,
                "rank": 1,
                "eligibility": thesis.eligibility.value,
                "overall_status": overall.value,
                "reasons": list(thesis.no_trade_reasons),
            },
            "screening_run_id,company_id",
        )
        if thesis.criteria:
            await self._request(
                "POST",
                "criterion_results",
                params={"on_conflict": "screening_result_id,criterion"},
                payload=[
                    {
                        "owner_id": owner_id,
                        "screening_result_id": result["id"],
                        "criterion": item.criterion,
                        "status": item.status.value,
                        "formula": item.formula,
                        "result": item.model_dump(mode="json")["values"],
                        "reason": item.reason,
                        "evidence_as_of": generated,
                    }
                    for item in thesis.criteria
                ],
                prefer="resolution=merge-duplicates",
            )
        for evidence in thesis.evidence:
            await self._request(
                "POST",
                "evidence_items",
                params={"on_conflict": "owner_id,provider,content_hash"},
                payload={
                    "owner_id": owner_id,
                    "company_id": company["id"],
                    "screening_result_id": result["id"],
                    "provider": evidence.provenance.provider,
                    "evidence_type": "provider_input",
                    "title": evidence.title,
                    "source_url": evidence.provenance.source_url,
                    "published_at": evidence.provenance.source_as_of,
                    "fetched_at": evidence.provenance.fetched_at,
                    "content_hash": evidence.evidence_id,
                    "provenance": evidence.provenance.model_dump(mode="json"),
                },
                prefer="resolution=merge-duplicates",
            )
        await self._request(
            "POST",
            "analysis_snapshots",
            params={"on_conflict": "owner_id,symbol,generated_at"},
            payload={
                "owner_id": owner_id,
                "company_id": company["id"],
                "symbol": thesis.company.ticker,
                "report_date": thesis.valuation.report_date,
                "generated_at": generated,
                "fresh_until": fresh_until.astimezone(UTC).isoformat(),
                "data_state": thesis.data_state.value,
                "thesis": raw,
            },
            prefer="resolution=merge-duplicates",
        )
        await self._request(
            "POST",
            "audit_events",
            params={"on_conflict": "owner_id,idempotency_key"},
            payload={
                "owner_id": owner_id,
                "actor_id": owner_id,
                "correlation_id": str(uuid5(NAMESPACE_URL, key)),
                "event_type": "analysis.completed",
                "entity_type": "screening_result",
                "entity_id": result["id"],
                "inputs_hash": self._hash(thesis),
                "decision": thesis.eligibility.value,
                "provider_provenance": [
                    item.provenance.model_dump(mode="json") for item in thesis.evidence
                ],
                "sanitized_details": {"symbol": thesis.company.ticker},
                "idempotency_key": key,
            },
            prefer="resolution=ignore-duplicates",
        )

    async def latest_thesis(self, owner_id: str, symbol: str) -> CompanyThesis | None:
        rows = await self._request(
            "GET",
            "analysis_snapshots",
            params={
                "owner_id": f"eq.{owner_id}",
                "symbol": f"eq.{symbol.upper()}",
                "select": "thesis,fresh_until",
                "order": "generated_at.desc",
                "limit": "1",
            },
        )
        if not isinstance(rows, list) or not rows:
            return None
        thesis = CompanyThesis.model_validate(rows[0]["thesis"])
        fresh_until = datetime.fromisoformat(str(rows[0]["fresh_until"]).replace("Z", "+00:00"))
        if fresh_until < datetime.now(UTC):
            from app.domain.models import DataState, Eligibility

            thesis = thesis.model_copy(
                update={
                    "data_state": DataState.STALE,
                    "eligibility": Eligibility.NO_TRADE,
                    "no_trade_reasons": (*thesis.no_trade_reasons, "analysis_stale"),
                }
            )
        return thesis

    async def frozen_thesis(
        self, owner_id: str, symbol: str, report_date: date
    ) -> CompanyThesis | None:
        rows = await self._request(
            "GET",
            "analysis_snapshots",
            params={
                "owner_id": f"eq.{owner_id}",
                "symbol": f"eq.{symbol.upper()}",
                "report_date": f"eq.{report_date.isoformat()}",
                "select": "thesis",
                "order": "generated_at.desc",
                "limit": "1",
            },
        )
        if not isinstance(rows, list) or not rows:
            return None
        return CompanyThesis.model_validate(rows[0]["thesis"])

    async def save_watchlist(self, owner_id: str, theses: tuple[CompanyThesis, ...]) -> None:
        await self._ensure_owner(owner_id)
        generated = max((item.generated_at for item in theses), default=datetime.now(UTC))
        raw = [item.model_dump(mode="json") for item in theses]
        digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        run = await self._upsert_one(
            "screening_runs",
            {
                "owner_id": owner_id,
                "status": "succeeded",
                "strategy_version": "phase2-v1",
                "idempotency_key": f"watchlist:{digest}",
                "inputs_hash": digest,
                "started_at": generated,
                "completed_at": generated,
            },
            "owner_id,idempotency_key",
        )
        watchlist = await self._upsert_one(
            "watchlists",
            {
                "owner_id": owner_id,
                "screening_run_id": run["id"],
                "name": f"Venuz {generated.date().isoformat()}",
            },
            "owner_id,screening_run_id",
        )
        for rank, thesis in enumerate(theses, 1):
            company = await self._company(thesis)
            result = await self._upsert_one(
                "screening_results",
                {
                    "owner_id": owner_id,
                    "screening_run_id": run["id"],
                    "company_id": company["id"],
                    "rank": rank,
                    "eligibility": thesis.eligibility.value,
                    "overall_status": ("red" if thesis.no_trade_reasons else "green"),
                    "reasons": list(thesis.no_trade_reasons),
                },
                "screening_run_id,company_id",
            )
            await self._request(
                "POST",
                "watchlist_items",
                params={"on_conflict": "watchlist_id,screening_result_id"},
                payload={
                    "owner_id": owner_id,
                    "watchlist_id": watchlist["id"],
                    "screening_result_id": result["id"],
                    "rank": rank,
                },
                prefer="resolution=merge-duplicates",
            )
        await self._request(
            "POST",
            "watchlist_snapshots",
            payload={
                "owner_id": owner_id,
                "screening_run_id": run["id"],
                "generated_at": generated,
                "items": raw,
            },
        )

    async def latest_watchlist(self, owner_id: str) -> tuple[CompanyThesis, ...]:
        rows = await self._request(
            "GET",
            "watchlist_snapshots",
            params={
                "owner_id": f"eq.{owner_id}",
                "select": "items",
                "order": "generated_at.desc",
                "limit": "1",
            },
        )
        if not isinstance(rows, list) or not rows:
            return ()
        items = rows[0]["items"]
        return tuple(CompanyThesis.model_validate(item) for item in items)

    async def start_job(self, owner_id: str, key: str, job_type: str) -> str:
        await self._ensure_owner(owner_id)
        row = await self._upsert_one(
            "job_runs",
            {
                "owner_id": owner_id,
                "job_type": job_type,
                "status": "running",
                "progress": 1,
                "idempotency_key": key,
                "started_at": datetime.now(UTC).isoformat(),
            },
            "owner_id,idempotency_key",
        )
        return str(row["id"])

    async def finish_job(
        self, job_id: str, *, succeeded: bool, failure_code: str | None = None
    ) -> None:
        await self._request(
            "PATCH",
            "job_runs",
            params={"id": f"eq.{job_id}"},
            payload={
                "status": "succeeded" if succeeded else "failed",
                "progress": 100,
                "failure_code": failure_code,
                "failure_detail": None if succeeded else "Sanitized provider or data failure",
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
