"""Per-scenario tests for `scenarios.baseline` (open-source-arena slice 05)."""

from __future__ import annotations

from scenarios.baseline import Baseline
from world.scenario import NullScenario, Scenario, load_scenario
from world.sim import World


def test_baseline_loads_via_dotted_path() -> None:
    instance = load_scenario("scenarios.baseline")
    assert isinstance(instance, Baseline)
    assert isinstance(instance, NullScenario)
    assert isinstance(instance, Scenario)
    assert instance.seed == 42


def test_baseline_is_a_noop() -> None:
    """Baseline must not write overrides, trace entries, or events."""
    world = World(scenario=Baseline())
    world.reset(seed=42, scenario=Baseline())
    world.step(days=3)
    assert world.state.weather_overrides == {}
    assert world.state.scenario_trace == []
    # Stochastic events are still allowed (the day-loop sampler may
    # fire), but the scenario itself must not have injected any.
    for event in world.state.active_events:
        # Scenario-injected entries would not carry the event_rng's
        # sampler shape (they'd lack the usual fields). Be permissive
        # here — the contract is just "no scenario_trace entries".
        assert "type" in event


def test_baseline_byte_identical_to_no_scenario() -> None:
    """Attaching Baseline to a seed-42 world must produce the same RNG
    state and observables as running with no scenario at all (the
    NullScenario default)."""
    a = World()
    b = World(scenario=Baseline())
    a.reset(seed=42)
    b.reset(seed=42, scenario=Baseline())
    a.step(days=3)
    b.step(days=3)
    assert a.state.treasury == b.state.treasury
    assert int(a.state.population) == int(b.state.population)
    assert a.state.weather_now == b.state.weather_now
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()
