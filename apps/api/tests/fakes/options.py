from __future__ import annotations

from datetime import UTC, datetime

from app.domain.options import OptionFeed, OptionsCapability
from app.integrations.alpaca_options import OptionAccountActivity, OptionRemotePosition


class FakeOptionsGateway:
    def __init__(self, capability: OptionsCapability | None = None) -> None:
        self.capability_result = capability or OptionsCapability(
            status="available",
            options_approved_level=1,
            options_trading_level=1,
            options_buying_power_available=True,
            paper_endpoint_valid=True,
            option_assets_available=True,
            contracts_accessible=True,
            chains_accessible=True,
            snapshots_accessible=True,
            feed=OptionFeed.INDICATIVE,
            checked_at=datetime(2026, 9, 3, 14, 0, tzinfo=UTC),
        )
        self.positions: tuple[OptionRemotePosition, ...] = ()
        self.activities: tuple[OptionAccountActivity, ...] = ()
        self.capability_calls = 0

    async def capability(self) -> OptionsCapability:
        self.capability_calls += 1
        return self.capability_result

    async def option_positions(self) -> tuple[OptionRemotePosition, ...]:
        return self.positions

    async def option_activities(self, after: datetime) -> tuple[OptionAccountActivity, ...]:
        return tuple(item for item in self.activities if item.occurred_at > after)
