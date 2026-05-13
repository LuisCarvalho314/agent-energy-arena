"""Per-scenario tests for `scenarios.grid_stress` (open-source-arena slice 05)."""

from __future__ import annotations

from scenarios.grid_stress import GridStress
from world.scenario import Scenario, load_scenario
from world.sim import World


def _fresh_world() -> World:
    w = World(scenario=GridStress())
    w.reset(seed=42, scenario=GridStress())
    return w


def _step_to_day(w: World, target_day: int) -> None:
    """Advance the world until `state.day == target_day`. `world.step`
    caps at 7 days per call, so we chunk."""
    while w.state.day < target_day:
        remaining = target_day - w.state.day
        w.step(days=min(7, remaining))


def test_grid_stress_loads_via_dotted_path() -> None:
    instance = load_scenario("scenarios.grid_stress")
    assert isinstance(instance, GridStress)
    assert isinstance(instance, Scenario)
    assert instance.seed == 42


def test_grid_stress_consumes_no_random_numbers() -> None:
    """The scenario's `apply` must not draw from any RNG. Sample the
    sim/event/forecast streams before vs after a few apply calls and
    assert they're unchanged."""
    w = _fresh_world()
    s = GridStress()
    sim_before = w.sim_rng.bit_generator.state
    event_before = w.event_rng.bit_generator.state
    forecast_before = w.forecast_rng.bit_generator.state
    s.apply(w, 0)
    s.apply(w, 5)
    s.apply(w, 10)
    assert w.sim_rng.bit_generator.state == sim_before
    assert w.event_rng.bit_generator.state == event_before
    assert w.forecast_rng.bit_generator.state == forecast_before


def test_grid_stress_low_wind_fires_and_clears_on_documented_days() -> None:
    """First low-wind window is days [5, 25). At day == start the
    override must pin weather_now; at day == end the override must
    clear and the end-trace entry must land."""
    start, end, mps = GridStress.LOW_WIND_WINDOWS[0]
    w = _fresh_world()

    _step_to_day(w, start + 1)
    assert w.state.weather_overrides.get("wind_speed_mps") == mps
    assert w.state.weather_now["wind_speed_mps"] == mps
    assert {
        "day": start,
        "kind": "low_wind_start",
        "wind_mps": float(mps),
    } in w.state.scenario_trace

    _step_to_day(w, end + 1)
    assert "wind_speed_mps" not in w.state.weather_overrides
    assert {"day": end, "kind": "low_wind_end"} in w.state.scenario_trace


def test_grid_stress_heatwave_injected_on_documented_day() -> None:
    """First heatwave injection day is `HEATWAVE_DAYS[0]`. After we
    advance past it, active events must contain a scenario-shaped
    heatwave with the documented duration."""
    day = GridStress.HEATWAVE_DAYS[0]
    w = _fresh_world()
    _step_to_day(w, day + 1)
    heatwaves = [e for e in w.state.active_events if e.get("type") == "heatwave"]
    assert any(e["started_day"] == day for e in heatwaves)
    injected = next(e for e in heatwaves if e["started_day"] == day)
    assert injected["ends_day"] == day + GridStress.HEATWAVE_DURATION_DAYS
    assert injected["severity"] == GridStress.HEATWAVE_SEVERITY
    assert {
        "day": day,
        "kind": "heatwave_injected",
        "ends_day": day + GridStress.HEATWAVE_DURATION_DAYS,
    } in w.state.scenario_trace


def test_grid_stress_heatwave_expires_on_documented_day() -> None:
    """A scenario-injected heatwave on day D must expire (move from
    active to historical) when day reaches D + HEATWAVE_DURATION_DAYS."""
    day = GridStress.HEATWAVE_DAYS[0]
    duration = GridStress.HEATWAVE_DURATION_DAYS
    w = _fresh_world()
    _step_to_day(w, day + duration + 1)
    actives = [
        e
        for e in w.state.active_events
        if e.get("type") == "heatwave" and e.get("started_day") == day
    ]
    assert actives == []
    historicals = [
        e
        for e in w.state.historical_events
        if e.get("type") == "heatwave" and e.get("started_day") == day
    ]
    assert len(historicals) == 1
