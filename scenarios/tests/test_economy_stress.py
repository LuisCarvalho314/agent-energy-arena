"""Per-scenario tests for `scenarios.economy_stress` (open-source-arena slice 05)."""

from __future__ import annotations

from scenarios.economy_stress import EconomyStress
from world.scenario import Scenario, load_scenario
from world.sim import World


def _fresh_world() -> World:
    w = World(scenario=EconomyStress())
    w.reset(seed=42, scenario=EconomyStress())
    return w


def _step_to_day(w: World, target_day: int) -> None:
    """Advance the world until `state.day == target_day`. `world.step`
    caps at 7 days per call, so we chunk."""
    while w.state.day < target_day:
        remaining = target_day - w.state.day
        w.step(days=min(7, remaining))


def test_economy_stress_loads_via_dotted_path() -> None:
    instance = load_scenario("scenarios.economy_stress")
    assert isinstance(instance, EconomyStress)
    assert isinstance(instance, Scenario)
    assert instance.seed == 42


def test_economy_stress_consumes_no_random_numbers() -> None:
    w = _fresh_world()
    s = EconomyStress()
    sim_before = w.sim_rng.bit_generator.state
    event_before = w.event_rng.bit_generator.state
    forecast_before = w.forecast_rng.bit_generator.state
    s.apply(w, 0)
    s.apply(w, EconomyStress.FUEL_SHOCK_START_DAY)
    s.apply(w, EconomyStress.REGULATORY_DAY)
    assert w.sim_rng.bit_generator.state == sim_before
    assert w.event_rng.bit_generator.state == event_before
    assert w.forecast_rng.bit_generator.state == forecast_before


def test_fuel_shock_fires_and_clears_on_documented_days() -> None:
    """Fuel shock runs [FUEL_SHOCK_START_DAY, FUEL_SHOCK_END_DAY).
    Advancing into the window: shocked costs visible. Advancing past
    FUEL_SHOCK_END_DAY: costs restore to baseline."""
    start = EconomyStress.FUEL_SHOCK_START_DAY
    end = EconomyStress.FUEL_SHOCK_END_DAY
    w = _fresh_world()

    _step_to_day(w, start + 1)
    assert (
        w.state.plant_fuel_cost_per_mwh["coal_plant"] == EconomyStress.FUEL_SHOCK_COAL_USD_PER_MWH
    )
    assert w.state.plant_fuel_cost_per_mwh["gas_peaker"] == EconomyStress.FUEL_SHOCK_GAS_USD_PER_MWH
    assert any(
        e.get("kind") == "fuel_shock_start" and e.get("day") == start
        for e in w.state.scenario_trace
    )

    _step_to_day(w, end + 1)
    assert w.state.plant_fuel_cost_per_mwh["coal_plant"] == 12.0
    assert w.state.plant_fuel_cost_per_mwh["gas_peaker"] == 30.0
    assert any(
        e.get("kind") == "fuel_shock_end" and e.get("day") == end for e in w.state.scenario_trace
    )


def test_fuel_shock_marker_visible_then_expires_to_history() -> None:
    """The fuel shock is applied by a silent price mutation, so a
    display-only `fuel_cost_shock` marker must surface it in active_events
    during the window and move to historical_events once it closes."""
    start = EconomyStress.FUEL_SHOCK_START_DAY
    end = EconomyStress.FUEL_SHOCK_END_DAY
    w = _fresh_world()

    _step_to_day(w, start + 1)
    active = [e for e in w.state.active_events if e.get("type") == "fuel_cost_shock"]
    assert len(active) == 1
    assert active[0]["started_day"] == start
    assert active[0]["ends_day"] == end
    assert active[0]["coal_usd_per_mwh"] == EconomyStress.FUEL_SHOCK_COAL_USD_PER_MWH
    assert active[0]["gas_usd_per_mwh"] == EconomyStress.FUEL_SHOCK_GAS_USD_PER_MWH

    _step_to_day(w, end + 1)
    assert not any(e.get("type") == "fuel_cost_shock" for e in w.state.active_events)
    assert any(e.get("type") == "fuel_cost_shock" for e in w.state.historical_events)


def test_crude_collapse_marker_visible_in_active_events() -> None:
    start = EconomyStress.CRUDE_COLLAPSE_START_DAY
    w = _fresh_world()
    _step_to_day(w, start + 1)
    markers = [e for e in w.state.active_events if e.get("type") == "crude_collapse"]
    assert len(markers) == 1
    assert markers[0]["crude_usd_per_bbl"] == EconomyStress.CRUDE_COLLAPSE_USD_PER_BBL


def test_crude_collapse_fires_on_documented_day() -> None:
    start = EconomyStress.CRUDE_COLLAPSE_START_DAY
    w = _fresh_world()
    _step_to_day(w, start + 1)
    assert w.state.crude_price_usd_per_bbl == EconomyStress.CRUDE_COLLAPSE_USD_PER_BBL
    assert any(
        e.get("kind") == "crude_collapse_start" and e.get("day") == start
        for e in w.state.scenario_trace
    )


def test_regulatory_tightening_fires_once_on_documented_day() -> None:
    """The carbon-price bump must apply on REGULATORY_DAY exactly
    once, and a `regulatory_tightening` marker must land in
    active_events with the configured duration."""
    day = EconomyStress.REGULATORY_DAY
    w = _fresh_world()
    carbon_before = w.state.carbon_price
    _step_to_day(w, day + 1)

    # carbon_price was bumped by REGULATORY_CARBON_PRICE_MULT — could
    # have been further bumped by a stochastic regulatory_tightening,
    # but the scenario's bump must be at least the multiplier.
    assert w.state.carbon_price >= (carbon_before * EconomyStress.REGULATORY_CARBON_PRICE_MULT)

    # Exactly one scenario-injected marker.
    markers = [
        e
        for e in w.state.active_events + w.state.historical_events
        if e.get("type") == "regulatory_tightening" and e.get("started_day") == day
    ]
    assert len(markers) == 1
    assert markers[0]["ends_day"] == day + EconomyStress.REGULATORY_DURATION_DAYS
    assert any(
        e.get("kind") == "regulatory_tightening_injected" and e.get("day") == day
        for e in w.state.scenario_trace
    )

    # Idempotent within the same day — re-applying must not double-bump.
    bumped = w.state.carbon_price
    EconomyStress().apply(w, day)
    assert w.state.carbon_price == bumped
