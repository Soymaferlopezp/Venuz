from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import alpaca
import pytest

from app.core.config import Settings
from app.factory import create_app
from app.repositories.orders import MemoryOrderRepository
from tests.fakes.broker import FakeBroker


def test_runtime_alpaca_resolves_to_pinned_third_party_distribution() -> None:
    imported = Path(str(alpaca.__file__)).resolve()
    local_source = Path(__file__).parents[1] / "app"
    assert version("alpaca-py") == "0.44.0"
    assert not imported.is_relative_to(local_source)
    assert "site-packages" in imported.parts


def test_missing_alpaca_py_stops_application_import() -> None:
    script = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'alpaca' or name.startswith('alpaca.'):
        raise ModuleNotFoundError('alpaca-py intentionally unavailable')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
import app.factory
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "alpaca-py intentionally unavailable" in result.stderr


def test_test_mode_requires_explicit_network_free_dependencies(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="network-free"):
        create_app(settings)


def test_broker_override_is_forbidden_outside_test(
    valid_settings_data: dict[str, Any],
) -> None:
    valid_settings_data["app_env"] = "development"
    production_like = Settings(_env_file=None, **valid_settings_data)
    with pytest.raises(RuntimeError, match="forbidden"):
        create_app(
            production_like,
            broker_override=FakeBroker(),
            order_repository_override=MemoryOrderRepository(),
        )
