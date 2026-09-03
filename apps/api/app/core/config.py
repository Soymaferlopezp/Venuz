from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PAPER_TRADING_URL = "https://paper-api.alpaca.markets"
LIVE_TRADING_HOST = "api.alpaca.markets"


def _parse_origins(value: object) -> object:
    if isinstance(value, str):
        return [origin.strip() for origin in value.split(",") if origin.strip()]
    return value


CorsOrigins = Annotated[list[AnyHttpUrl], NoDecode, BeforeValidator(_parse_origins)]


class Settings(BaseSettings):
    """Server-only settings whose values stay hidden in validation errors."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_cors_origins: CorsOrigins = Field(
        default_factory=lambda: [AnyHttpUrl("http://localhost:3000")]
    )
    app_timezone: str = "America/New_York"
    strategy_version: str = Field(default="2026.09", min_length=1, max_length=32)

    supabase_url: AnyHttpUrl
    supabase_secret_key: SecretStr = Field(min_length=1)
    supabase_database_url: SecretStr = Field(min_length=1)
    alpaca_api_key: SecretStr = Field(min_length=1)
    alpaca_secret_key: SecretStr = Field(min_length=1)
    alpaca_trading_base_url: AnyHttpUrl = AnyHttpUrl(PAPER_TRADING_URL)
    alpaca_data_base_url: AnyHttpUrl = AnyHttpUrl("https://data.alpaca.markets")
    alpaca_paper: bool = True

    sec_user_agent: str = Field(min_length=8)
    alpha_vantage_api_key: SecretStr = Field(min_length=1)
    alpha_vantage_daily_request_budget: int = Field(default=25, ge=1, le=25)
    gemini_api_key: SecretStr = Field(min_length=1)
    gemini_model: str = Field(min_length=1)
    openrouter_api_key: SecretStr = Field(min_length=1)
    openrouter_model: str = Field(min_length=1)
    openrouter_base_url: AnyHttpUrl = AnyHttpUrl("https://openrouter.ai/api/v1")

    trading_mode: Literal["paper"] = "paper"
    auto_execution_enabled: bool = False
    human_approval_enabled: bool = True
    max_position_pct: Decimal = Field(default=Decimal("0.10"), ge=0, le=Decimal("0.10"))
    min_cash_pct: Decimal = Field(default=Decimal("0.20"), ge=Decimal("0.20"), le=1)
    max_sector_pct: Decimal = Field(default=Decimal("0.20"), ge=0, le=Decimal("0.20"))
    max_companies_per_sector: int = Field(default=2, ge=1, le=2)

    @model_validator(mode="after")
    def enforce_paper_only(self) -> Self:
        trading_url = str(self.alpaca_trading_base_url).rstrip("/")
        hostname = (urlsplit(trading_url).hostname or "").lower()
        if hostname == LIVE_TRADING_HOST:
            raise ValueError("Alpaca Live endpoint detected; Venuz is paper-only")
        if trading_url != PAPER_TRADING_URL:
            raise ValueError(f"Alpaca trading endpoint must be exactly {PAPER_TRADING_URL}")
        if not self.alpaca_paper:
            raise ValueError("ALPACA_PAPER must be true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
