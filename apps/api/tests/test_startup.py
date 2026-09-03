import os
import subprocess
import sys
from typing import Any


def _startup_environment(settings: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    for key, value in settings.items():
        if isinstance(value, list):
            rendered = ",".join(value)
        elif isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = str(value)
        environment[key.upper()] = rendered
    return environment


def test_process_refuses_live_endpoint_without_exposing_inputs(
    valid_settings_data: dict[str, Any],
) -> None:
    environment = _startup_environment(valid_settings_data)
    environment["ALPACA_TRADING_BASE_URL"] = "https://api.alpaca.markets"

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "Alpaca Live endpoint detected" in result.stderr
    assert "test-paper-secret" not in result.stderr
    assert "input_value=" not in result.stderr


def test_process_starts_with_exact_paper_configuration(valid_settings_data: dict[str, Any]) -> None:
    environment = _startup_environment(valid_settings_data)
    environment["APP_ENV"] = "production"
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, "safe app entrypoint should import successfully"
