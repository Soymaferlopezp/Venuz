from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import PAPER_TRADING_URL, Settings, get_settings


def build_settings(data: dict[str, Any]) -> Settings:
    return Settings(_env_file=None, **data)


@pytest.mark.parametrize("trading_mode", ["live", "sandbox", "PAPER"])
def test_rejects_any_non_paper_trading_mode(
    valid_settings_data: dict[str, Any], trading_mode: str
) -> None:
    valid_settings_data["trading_mode"] = trading_mode

    with pytest.raises(ValidationError, match="paper"):
        build_settings(valid_settings_data)


def test_rejects_false_alpaca_paper_flag(valid_settings_data: dict[str, Any]) -> None:
    valid_settings_data["alpaca_paper"] = False

    with pytest.raises(ValidationError, match="ALPACA_PAPER must be true"):
        build_settings(valid_settings_data)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.example",
        "https://example.com",
    ],
)
def test_rejects_live_or_non_allowlisted_trading_endpoint(
    valid_settings_data: dict[str, Any], url: str
) -> None:
    valid_settings_data["alpaca_trading_base_url"] = url

    with pytest.raises(ValidationError, match="paper-only|must be exactly"):
        build_settings(valid_settings_data)


def test_accepts_exact_paper_endpoint(valid_settings_data: dict[str, Any]) -> None:
    settings = build_settings(valid_settings_data)

    assert str(settings.alpaca_trading_base_url).rstrip("/") == PAPER_TRADING_URL
    assert settings.trading_mode == "paper"
    assert settings.alpaca_paper is True


def test_secret_values_are_masked(valid_settings_data: dict[str, Any]) -> None:
    settings = build_settings(valid_settings_data)
    rendered = repr(settings)

    assert "test-paper-secret" not in rendered
    assert "**********" in rendered


def test_rejects_auto_execution_during_foundation(valid_settings_data: dict[str, Any]) -> None:
    valid_settings_data["auto_execution_enabled"] = True

    with pytest.raises(ValidationError, match="must remain false"):
        build_settings(valid_settings_data)


def test_loads_comma_separated_cors_origins_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, valid_settings_data: dict[str, Any]
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in valid_settings_data.items():
        if key == "app_cors_origins":
            value = "http://localhost:3000,https://venuz.example"
        monkeypatch.setenv(key.upper(), str(value))
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("AUTO_EXECUTION_ENABLED", "false")
    get_settings.cache_clear()

    settings = get_settings()

    assert [str(origin).rstrip("/") for origin in settings.app_cors_origins] == [
        "http://localhost:3000",
        "https://venuz.example",
    ]
    get_settings.cache_clear()
