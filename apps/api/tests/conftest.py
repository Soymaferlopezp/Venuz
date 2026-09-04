from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import PAPER_TRADING_URL, Settings
from app.factory import create_app
from app.repositories.options import MemoryOptionRepository
from app.repositories.orders import MemoryOrderRepository
from tests.fakes.broker import FakeBroker
from tests.fakes.options import FakeOptionsGateway


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def valid_settings_data() -> dict[str, Any]:
    return {
        "app_env": "test",
        "app_cors_origins": ["http://localhost:3000"],
        "supabase_url": "https://example.supabase.co",
        "supabase_secret_key": "test-supabase-secret",
        "supabase_database_url": "postgresql://test.invalid/postgres",
        "alpaca_api_key": "test-paper-key",
        "alpaca_secret_key": "test-paper-secret",
        "alpaca_trading_base_url": PAPER_TRADING_URL,
        "alpaca_paper": True,
        "sec_user_agent": "Venuz test@example.com",
        "alpha_vantage_api_key": "test-alpha-vantage-key",
        "gemini_api_key": "test-gemini-key",
        "gemini_model": "test-model",
        "openrouter_api_key": "test-openrouter-key",
        "openrouter_model": "test/model:free",
        "trading_mode": "paper",
        "auto_execution_enabled": False,
    }


@pytest.fixture
def settings(valid_settings_data: dict[str, Any]) -> Settings:
    return Settings(_env_file=None, **valid_settings_data)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(
        create_app(
            settings,
            broker_override=FakeBroker(),
            order_repository_override=MemoryOrderRepository(),
            options_gateway_override=FakeOptionsGateway(),
            options_repository_override=MemoryOptionRepository(),
        )
    ) as test_client:
        yield test_client
