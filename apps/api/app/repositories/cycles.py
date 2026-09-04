from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.options import CycleMode, OptionsCapability
from app.repositories.analysis import SupabaseRestStore
from app.services.cycles import CycleEvent, PublicCycle


class SupabaseCycleRepository:
    """Durable repository backed by atomic Postgres RPCs."""

    def __init__(self, store: SupabaseRestStore) -> None:
        self.store = store

    async def _rpc(self, function: str, payload: Mapping[str, object]) -> Any:
        response = await self.store.client.post(
            f"{self.store.base_url}/rest/v1/rpc/{function}",
            headers=self.store._headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _cycle(row: Mapping[str, Any], *, historical: bool = False) -> PublicCycle:
        events = tuple(CycleEvent.model_validate(item) for item in row.get("events", []))
        return PublicCycle(
            cycle_id=str(row["cycle_id"]),
            cycle_key=str(row["cycle_key"]),
            mode=str(row.get("mode", "stocks")),
            selected_asset_class=row.get("selected_asset_class"),
            options_capability_status=str(row.get("options_capability_status", "not_required")),
            state=str(row["state"]),
            historical=historical,
            data_freshness=str(row.get("data_freshness", "fresh")),
            paper_order_submitted=bool(row.get("paper_order_submitted", False)),
            blocked_reasons=tuple(row.get("blocked_reasons", [])),
            evidence_links=tuple(row.get("evidence_links", [])),
            provider_provenance=tuple(row.get("provider_provenance", [])),
            events=events,
            updated_at=row["updated_at"],
        )

    async def activate(
        self,
        key: str,
        now: datetime,
        mode: CycleMode = CycleMode.STOCKS,
        capability: OptionsCapability | None = None,
    ) -> PublicCycle:
        row = await self._rpc(
            "activate_global_cycle_mode",
            {
                "p_cycle_key": key,
                "p_mode": mode.value,
                "p_now": now.isoformat(),
                "p_options_capability_status": (
                    capability.status if capability is not None else "not_required"
                ),
                "p_blocked_reasons": list(
                    capability.blocking_reasons if capability is not None else ()
                ),
            },
        )
        if not isinstance(row, Mapping):
            raise RuntimeError("Invalid cycle activation response")
        return self._cycle(row)

    async def get(self, cycle_id: str) -> PublicCycle | None:
        response = await self.store.client.get(
            f"{self.store.base_url}/rest/v1/public_cycle_envelopes",
            headers=self.store._headers,
            params={"cycle_id": f"eq.{cycle_id}", "limit": "1"},
            timeout=15,
        )
        response.raise_for_status()
        rows = response.json()
        return self._cycle(rows[0]) if isinstance(rows, list) and rows else None

    async def latest(self) -> PublicCycle | None:
        response = await self.store.client.get(
            f"{self.store.base_url}/rest/v1/public_cycle_envelopes",
            headers=self.store._headers,
            params={"order": "updated_at.desc", "limit": "1"},
            timeout=15,
        )
        response.raise_for_status()
        rows = response.json()
        return self._cycle(rows[0], historical=True) if isinstance(rows, list) and rows else None
