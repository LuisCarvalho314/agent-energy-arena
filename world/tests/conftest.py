"""Test-only compatibility for mechanics tests unrelated to transmission.

Most pre-transmission tests place isolated generators or consumers to focus on
dispatch, economy, population, or API behavior. Those tests should not have to
build a miniature grid. The real connectivity rules remain active in
``test_grid.py``; every other legacy test sees all tiles as connected.
"""

from __future__ import annotations

from typing import Any

import pytest


def _assume_connected(*_args: Any, **_kwargs: Any) -> bool:
    return True


def _assume_grid_factor(*_args: Any, **_kwargs: Any) -> float:
    return 1.0


@pytest.fixture(autouse=True)
def legacy_power_connectivity(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Assume power connectivity in legacy tests unless they test grid rules."""
    if request.node.path.name == "test_grid.py":
        return

    from world import economy, hourly_tick, population, power, sim, state_view

    monkeypatch.setattr(economy, "connected_to_power", _assume_connected)
    monkeypatch.setattr(hourly_tick, "connected_to_power", _assume_connected)
    monkeypatch.setattr(population, "connected_to_power", _assume_connected)
    monkeypatch.setattr(power, "connected_to_power", _assume_connected)
    monkeypatch.setattr(power, "power_source_connected", _assume_connected)
    monkeypatch.setattr(sim, "connected_to_power", _assume_connected)
    monkeypatch.setattr(state_view, "connected_to_power", _assume_connected)
    monkeypatch.setattr(state_view, "grid_factor_with_consumers", _assume_grid_factor)
    monkeypatch.setattr(state_view, "has_power_connection", _assume_connected)
    monkeypatch.setattr(state_view, "is_grid_connected", _assume_connected)
    monkeypatch.setattr(state_view, "power_source_connected", _assume_connected)
