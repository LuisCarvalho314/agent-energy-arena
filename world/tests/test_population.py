"""Population dynamics and daily tax revenue (slice 03).

Each cascading branch of `update_population` is exercised in isolation by
manipulating tiles/population/blackout-hours directly, so the test asserts
on the algebra from §4.8 of the brief rather than going end-to-end through
multiple build calls.
"""

from __future__ import annotations

import pytest

from world.population import DAILY_TAX_PER_CAPITA, update_population
from world.sim import World
from world.state import Tile


def _fresh_world() -> World:
    w = World()
    w.reset(seed=42)
    return w


def _inject_tile(
    w: World,
    *,
    type: str,
    x: int,
    y: int,
    jobs: int = 0,
    housing_capacity: int = 0,
) -> None:
    """Bypass /build's adjacency/funds checks to set up arbitrary aggregates."""
    w.state.tiles.append(
        Tile(
            id=f"injected-{x}-{y}",
            type=type,
            x=x,
            y=y,
            built_day=0,
            operational=True,
            jobs=jobs,
            housing_capacity=housing_capacity,
        )
    )


# -- Branch 1: growth --------------------------------------------------------


def test_grow_branch_applies_base_rate_capped_by_headroom():
    """jobs >= pop AND capacity > pop AND happiness >= 0.5 → grow."""
    w = _fresh_world()
    # Town hall already gives capacity=100, jobs=30. Inject a synthetic block
    # with abundant headroom so the cap on growth is the base rate, not
    # capacity/jobs headroom.
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 500

    update_population(w)

    # happiness = 1.0 (no parks, no blackouts, no coal).
    # growth = min(0.012 * 500 * 1.0 = 6.0, cap-pop=600, jobs-pop=530) = 6.0.
    assert w.state.population == 506
    assert w.state.happiness == pytest.approx(1.0)


def test_grow_branch_capped_by_jobs_headroom():
    w = _fresh_world()
    # capacity = 100 + 1000 = 1100; jobs = 30 + (1000) tied at +1 above pop.
    _inject_tile(w, type="commercial", x=5, y=5, jobs=71, housing_capacity=1000)
    # pop=100, jobs=101. jobs - pop = 1, far below 0.012*100=1.2.
    w.state.population = 100

    update_population(w)
    # growth = min(1.2, 1100-100=1000, 101-100=1) = 1. New pop = 101.
    assert w.state.population == 101


# -- Branch 2: housing exodus ------------------------------------------------


def test_exodus_when_capacity_drops_below_pop():
    """capacity < pop → pop = max(capacity, pop - 5)."""
    w = _fresh_world()
    # Town hall capacity=100. Set pop=110 (above capacity).
    w.state.population = 110

    update_population(w)
    # max(100, 110 - 5) = 105.
    assert w.state.population == 105


def test_exodus_floors_at_capacity():
    w = _fresh_world()
    # Capacity = 100. Pop just above; pop - 5 < capacity.
    w.state.population = 102

    update_population(w)
    # max(100, 102 - 5 = 97) = 100.
    assert w.state.population == 100


# -- Branch 3: job-driven decline --------------------------------------------


def test_job_decline_one_day_from_fresh_world():
    """Fresh world: pop=100, jobs=30. jobs < 0.7*pop=70 → pop=max(42.857, 99.0)=99."""
    w = _fresh_world()
    update_population(w)
    assert w.state.population == 99
    assert w.state.happiness == pytest.approx(1.0)


def test_job_decline_70_days_approaches_equilibrium():
    """After 70 simulated days, pop floors at jobs/0.7 ≈ 42-43."""
    w = _fresh_world()
    w.step(days=7)
    for _ in range(9):
        w.step(days=7)
    # int truncation lands the equilibrium at floor(30/0.7) = 42.
    assert 40 <= w.state.population <= 45


# -- Branch 4: happiness decline ---------------------------------------------


def test_happiness_decline_when_below_threshold():
    """jobs >= pop AND cap > pop but happiness < 0.5 → pop *= 0.99."""
    w = _fresh_world()
    # Inject abundant capacity+jobs so the first three branches are skipped.
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 100
    # Happiness term is `-0.10 * (yest_blackout_hours / 24)`. To force
    # happiness below 0.5 we need penalty > 0.5, i.e. blackout_hours > 120.
    w.state.yesterday_blackout_hours = 200.0

    update_population(w)
    # happiness = 1.0 - 0.10 * 200/24 ≈ 0.167 (below 0.5 threshold).
    assert w.state.happiness < 0.5
    # pop = 100 * 0.99 = 99.
    assert w.state.population == 99


# -- Tax revenue -------------------------------------------------------------


def test_tax_revenue_accrues_to_treasury_and_summary():
    """Tax = $4 × end-of-day population, accrued to treasury + summary.

    Calls update_population directly so the assertion stays focused on the
    population module's contract (slice 03). Going through step would now
    mix in dispatch-driven blackout penalties from slice 05.
    """
    w = _fresh_world()
    treasury_before = w.state.treasury
    update_population(w)
    # pop went 100 → 99 (job-decline branch).
    assert w.state.population == 99
    assert w.state.today_summary_so_far["tax_revenue"] == pytest.approx(99 * 4.0)
    assert w.state.treasury == pytest.approx(treasury_before + 99 * 4.0)


def test_tax_revenue_constant_per_capita():
    """DAILY_TAX_PER_CAPITA is the brief's named constant ($4)."""
    assert DAILY_TAX_PER_CAPITA == 4.0


# -- Happiness composition ---------------------------------------------------


def test_park_count_bonus_kicks_in_after_first_park():
    """Happiness gains 0.05 per park beyond the first."""
    w = _fresh_world()
    _inject_tile(w, type="park", x=1, y=1)
    _inject_tile(w, type="park", x=2, y=2)
    _inject_tile(w, type="park", x=3, y=3)

    update_population(w)
    # park_count=3 → bonus = 0.05 * (3-1) = 0.10. happiness = 1.10.
    assert w.state.happiness == pytest.approx(1.10)


def test_happiness_clipped_above_at_1_5():
    w = _fresh_world()
    # Stuff in 50 parks → bonus = 0.05*49 = 2.45 → clipped at 1.5.
    for i in range(50):
        _inject_tile(w, type="park", x=i, y=0)

    update_population(w)
    assert w.state.happiness == pytest.approx(1.5)


def test_happiness_clipped_below_at_0_0():
    w = _fresh_world()
    # Crank blackout hours absurdly high; happiness would go very negative.
    w.state.yesterday_blackout_hours = 10_000.0

    update_population(w)
    assert w.state.happiness == pytest.approx(0.0)


# -- State surface -----------------------------------------------------------


def test_state_dict_exposes_population_and_happiness():
    w = _fresh_world()
    s = w.state_dict()
    assert "population" in s
    assert "happiness" in s
    assert s["population"] == 100
    assert s["happiness"] == pytest.approx(1.0)


def test_step_size_invariance_with_population_dynamics():
    """Slice-01 determinism contract holds with population update wired in."""
    a = World()
    a.reset(seed=42)
    a.step(days=7)

    b = World()
    b.reset(seed=42)
    for _ in range(7):
        b.step(days=1)

    assert a.state.treasury == b.state.treasury
    assert a.state.population == b.state.population
    assert a.state.happiness == b.state.happiness
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()
