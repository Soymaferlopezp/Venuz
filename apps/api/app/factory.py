from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import router as analysis_router
from app.api.cycles import router as cycles_router
from app.api.health import router as health_router
from app.api.options import router as options_router
from app.api.order_observation import router as order_observation_router
from app.core.config import Settings
from app.integrations.alpaca import AlpacaReadClient
from app.integrations.alpaca_broker import AlpacaPyBroker
from app.integrations.alpaca_options import AlpacaOptionsGateway, OptionsGateway
from app.integrations.alpaca_sdk import create_paper_read_clients
from app.integrations.alpha_vantage import AlphaVantageClient, BudgetStore, MemoryBudgetStore
from app.integrations.base import AsyncJsonClient, CacheStore, MemoryCacheStore
from app.integrations.broker import Broker
from app.integrations.sec import SecEdgarClient
from app.repositories.analysis import (
    AnalysisRepository,
    MemoryAnalysisRepository,
    SupabaseAnalysisRepository,
    SupabaseRestStore,
)
from app.repositories.cycles import SupabaseCycleRepository
from app.repositories.options import OptionRepository, SupabaseOptionRepository
from app.repositories.orders import OrderRepository, SupabaseOrderRepository
from app.services.cycles import MemoryCycleRepository
from app.services.options import OptionsService
from app.services.orders import OrderLifecycleService
from app.services.provider_analysis import ProviderAnalysisService


def create_app(
    settings: Settings,
    *,
    broker_override: Broker | None = None,
    order_repository_override: OrderRepository | None = None,
    options_gateway_override: OptionsGateway | None = None,
    options_repository_override: OptionRepository | None = None,
) -> FastAPI:
    if settings.app_env == "test" and (
        broker_override is None
        or order_repository_override is None
        or options_gateway_override is None
        or options_repository_override is None
    ):
        raise RuntimeError("Test mode requires explicit network-free order dependencies")
    if settings.app_env != "test" and (
        broker_override is not None
        or order_repository_override is not None
        or options_gateway_override is not None
        or options_repository_override is not None
    ):
        raise RuntimeError("Broker overrides are forbidden outside test mode")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        client = httpx.AsyncClient()
        app.state.http_client = client
        repository: AnalysisRepository
        cache: CacheStore
        budget: BudgetStore
        if settings.app_env == "test":
            repository = MemoryAnalysisRepository()
            cache = MemoryCacheStore()
            budget = MemoryBudgetStore()
        else:
            store = SupabaseRestStore(
                str(settings.supabase_url),
                settings.supabase_secret_key.get_secret_value(),
                client,
            )
            repository = SupabaseAnalysisRepository(store)
            cache = store
            budget = store
        app.state.analysis_repository = repository
        app.state.analysis_service = ProviderAnalysisService(
            repository,
            SecEdgarClient(
                AsyncJsonClient(provider="sec_edgar", client=client, cache=cache),
                settings.sec_user_agent,
            ),
            AlpacaReadClient(
                AsyncJsonClient(provider="alpaca", client=client, cache=cache),
                settings.alpaca_api_key.get_secret_value(),
                settings.alpaca_secret_key.get_secret_value(),
            ),
            AlphaVantageClient(
                AsyncJsonClient(provider="alpha_vantage", client=client, cache=cache),
                budget,
                settings.alpha_vantage_api_key.get_secret_value(),
                settings.alpha_vantage_daily_request_budget,
            ),
        )
        app.state.provider_store = budget
        app.state.cycle_repository = (
            MemoryCycleRepository()
            if settings.app_env == "test"
            else SupabaseCycleRepository(store)
        )
        if settings.app_env == "test":
            assert broker_override is not None
            assert order_repository_override is not None
            assert options_gateway_override is not None
            assert options_repository_override is not None
            app.state.order_repository = order_repository_override
            app.state.options_repository = options_repository_override
            app.state.options_gateway = options_gateway_override
            app.state.broker = broker_override
        else:
            app.state.order_repository = SupabaseOrderRepository(store)
            app.state.options_repository = SupabaseOptionRepository(store)
            sdk = create_paper_read_clients(
                settings.alpaca_api_key.get_secret_value(),
                settings.alpaca_secret_key.get_secret_value(),
            )
            app.state.broker = AlpacaPyBroker(sdk.trading)
            app.state.options_gateway = AlpacaOptionsGateway(
                sdk.trading,
                sdk.option_data,
                client,
                settings.alpaca_api_key.get_secret_value(),
                settings.alpaca_secret_key.get_secret_value(),
            )
        app.state.order_service = OrderLifecycleService(
            app.state.order_repository,
            app.state.broker,
            auto_execution_enabled=settings.auto_execution_enabled,
        )
        app.state.options_service = OptionsService(
            app.state.options_repository,
            app.state.broker,
            app.state.options_gateway,
            auto_execution_enabled=settings.auto_execution_enabled,
        )
        try:
            yield
        finally:
            await client.aclose()

    application = FastAPI(
        title="Venuz API",
        version="0.1.0",
        description="Deterministic, paper-only foundation for Venuz.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.app_cors_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    application.include_router(health_router)
    application.include_router(analysis_router)
    application.include_router(cycles_router)
    application.include_router(order_observation_router)
    application.include_router(options_router)
    return application
