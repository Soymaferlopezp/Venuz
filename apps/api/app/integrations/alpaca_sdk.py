from __future__ import annotations

from dataclasses import dataclass

from alpaca.data.historical import NewsClient, StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.trading.client import TradingClient


@dataclass(frozen=True)
class AlpacaSdkClients:
    trading: TradingClient
    market_data: StockHistoricalDataClient
    news: NewsClient
    option_data: OptionHistoricalDataClient


def create_paper_read_clients(api_key: str, secret_key: str) -> AlpacaSdkClients:
    """Create official SDK clients; trading is permanently bound to Alpaca Paper."""
    return AlpacaSdkClients(
        trading=TradingClient(api_key, secret_key, paper=True),
        market_data=StockHistoricalDataClient(api_key, secret_key),
        news=NewsClient(api_key, secret_key),
        option_data=OptionHistoricalDataClient(api_key, secret_key),
    )
