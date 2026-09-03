from alpaca.common.enums import BaseURL

from app.integrations.alpaca_sdk import create_paper_read_clients


def test_official_alpaca_sdk_factory_is_paper_only() -> None:
    clients = create_paper_read_clients("fixture-key", "fixture-secret")
    assert clients.trading._base_url == BaseURL.TRADING_PAPER
    assert clients.market_data.__class__.__name__ == "StockHistoricalDataClient"
    assert clients.news.__class__.__name__ == "NewsClient"
