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
    staffed_jobs: int | None = None,
    built_day: int = 0,
    operational: bool = True,
) -> None:
    """Bypass /build's adjacency/funds checks to set up arbitrary aggregates.

    Workforce slice 01: defaults ``staffed_jobs`` to ``jobs`` so injected
    producer tiles look fully staffed. Tests that want a partially-staffed
    tile pass ``staffed_jobs=N`` explicitly.
    """
    from world.catalog import TILE_CATALOG

    spec = TILE_CATALOG.get(type)
    w.state.tiles.append(
        Tile(
            id=f"injected-{x}-{y}",
            type=type,
            x=x,
            y=y,
            built_day=built_day,
            operational=operational,
            jobs=jobs,
            housing_capacity=housing_capacity,
            demand_kw=spec.demand_kw if spec is not None else 0.0,
            staffed_jobs=jobs if staffed_jobs is None else staffed_jobs,
        )
    )


# -- Branch 1: growth --------------------------------------------------------


def test_grow_branch_applies_base_rate_capped_by_headroom():
    """jobs >= pop AND capacity > pop AND happiness >= 0.3 → grow."""
    w = _fresh_world()
    # Town hall already gives capacity=100, jobs=30. Inject a synthetic block
    # with abundant headroom so the cap on growth is the base rate, not
    # capacity/jobs headroom.
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 500

    update_population(w)

    # happiness = 1.0 (no parks, no blackouts, no coal).
    # growth_multiplier = (1.0 - 0.3) / 1.2 ≈ 0.5833.
    # growth = min(0.012 * 500 * 0.5833 ≈ 3.5, cap-pop=600, jobs-pop=530) ≈ 3.5.
    assert w.state.population == 503
    assert w.state.happiness == pytest.approx(1.0)


def test_grow_branch_capped_by_jobs_headroom():
    w = _fresh_world()
    # capacity = 100 + 1000 = 1100; jobs tied at +1 above pop.
    _inject_tile(w, type="commercial", x=5, y=5, jobs=471, housing_capacity=1000)
    # pop=500, jobs=501. jobs - pop = 1, far below 0.012*500*0.5833 ≈ 3.5.
    w.state.population = 500

    update_population(w)
    # growth = min(3.5, 1100-500=600, 501-500=1) = 1. New pop = 501.
    assert w.state.population == 501


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
    """After 70 simulated days, pop floors at jobs/0.7 ≈ 42-43.

    A gas peaker is force-placed so the fresh world isn't blacking out
    every hour — without it, the issue-22 happiness-decline branch
    cascades pop past the job-floor down toward 0."""
    w = _fresh_world()
    # Inject a fully-staffed gas peaker (workforce slice 04: catalog efficiency
    # zeroes dispatch for unstaffed plants).
    _inject_tile(w, type="gas_peaker", x=0, y=0, staffed_jobs=4)
    w.state.tiles[-1].current_output_kw = 0.0
    # Set the catalog-driven capacity field so dispatch sees a usable plant.
    w.state.tiles[-1].opex_per_day = 150.0
    # Mark capacity_kw via the tile-spec is implicit (catalog read on dispatch);
    # the gas peaker spec already provides 500 kW @ 50%/h ramp.
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
    # Per-hour blackout coefficient is BLACKOUT_HAPPINESS_PER_HOUR = 0.05.
    # 24h+ of blackouts saturates happiness at 0.0 (after [0, 1.5] clip).
    w.state.yesterday_blackout_hours = 200.0

    update_population(w)
    # happiness ≈ max(0, 1 - 0.05 * 200) = max(0, -9) = 0.
    assert w.state.happiness < 0.5
    # pop = 100 * 0.99 = 99.
    assert w.state.population == 99


def test_full_day_blackout_drops_happiness_below_threshold():
    """24h of blackout in a single day pins happiness at 0 (clipped)."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 100
    w.state.yesterday_blackout_hours = 24.0

    update_population(w)
    # 1.0 - 0.05 * 24 = -0.20 → clipped to 0.0.
    assert w.state.happiness == pytest.approx(0.0)
    # 100 * 0.99 = 99 → int → 99.
    assert w.state.population == 99


def test_thirteen_vs_fifteen_hour_blackout_crosses_decline_threshold():
    """Decline threshold is now `< 0.3` (PRD §3.3 smooth-growth rewrite).
    With coef 0.05/h, 13h leaves happiness at 0.35 (no decline; growth
    multiplier tiny but positive) and 15h drops it below 0.3 (decline fires).
    14h is avoided because 1.0 - 0.05*14 floats to 0.2999...9 < 0.3."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 100
    w.state.yesterday_blackout_hours = 13.0

    update_population(w)
    # 1.0 - 0.05 * 13 = 0.35 → growth branch fires (mult≈0.042 → +0).
    assert w.state.happiness == pytest.approx(0.35)
    assert w.state.population == 100

    # Re-run with 15h: decline fires.
    w2 = _fresh_world()
    _inject_tile(w2, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w2.state.population = 100
    w2.state.yesterday_blackout_hours = 15.0
    update_population(w2)
    assert w2.state.happiness < 0.3
    assert w2.state.population == 99


def test_brownout_hours_also_dent_happiness():
    """Brownout coefficient is lighter than blackout (0.02/h) but still
    accumulates: 24h brownout drops happiness by 0.48."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    w.state.population = 100
    w.state.yesterday_brownout_hours = 24.0

    update_population(w)
    # 1.0 - 0.02 * 24 = 0.52. Still ≥ 0.5 so no decline; verifies the term.
    assert w.state.happiness == pytest.approx(0.52)


def test_zero_blackout_no_pop_decline():
    """No blackout, jobs/capacity sufficient → pop grows; happiness stays at 1.0."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    # PRD §3.3 smooth gate: at h=1.0 the multiplier is 0.583, so pop must be
    # large enough that base_growth_rate × pop × 0.583 ≥ 1 to see an integer
    # increment (pop ≥ ~143). Use 300 to leave clear headroom.
    w.state.population = 300
    # Default: yesterday_blackout_hours = yesterday_brownout_hours = 0.

    update_population(w)
    assert w.state.happiness == pytest.approx(1.0)
    assert w.state.population > 300  # growth branch fires


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


def test_first_park_within_chebyshev_2_of_house_contributes():
    """PRD §3.3: first park within chebyshev-2 of a house adds 0.10 happiness.

    The old `0.05 * max(0, park_count - 1)` off-by-one is gone — a single
    park near a single house is worth the full 0.10 floor.
    """
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="park", x=1, y=1)  # chebyshev=1 ≤ 2

    update_population(w)
    # bonus_per_house = min(0.30, 0.10 * 1) = 0.10. park_benefit = 0.10.
    assert w.state.happiness == pytest.approx(1.10)


def test_park_outside_chebyshev_2_contributes_zero():
    """Park beyond chebyshev-2 of every house contributes nothing."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="park", x=5, y=5)  # chebyshev=5 > 2

    update_population(w)
    assert w.state.happiness == pytest.approx(1.0)


def test_park_benefit_caps_at_0_30_per_house():
    """min(0.30, 0.10 * nearby_parks) — 4+ parks near one house cap at 0.30."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    # All four parks within chebyshev-2 of the house.
    _inject_tile(w, type="park", x=1, y=1)
    _inject_tile(w, type="park", x=2, y=2)
    _inject_tile(w, type="park", x=-1, y=-1)
    _inject_tile(w, type="park", x=-2, y=-2)

    update_population(w)
    # bonus_per_house = min(0.30, 0.40) = 0.30.
    assert w.state.happiness == pytest.approx(1.30)


def test_park_benefit_zero_when_no_houses():
    """No house tiles → park_benefit=0 regardless of park count."""
    w = _fresh_world()
    for i in range(50):
        _inject_tile(w, type="park", x=i, y=0)

    update_population(w)
    # No houses → mean over zero houses is 0 by the PRD's fallback clause.
    assert w.state.happiness == pytest.approx(1.0)


def test_industrial_adjacent_to_house_drops_happiness():
    """Industrial within chebyshev-2 of a house contributes -0.03 noise."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="industrial", x=1, y=1, jobs=5)  # chebyshev=1 ≤ 2

    update_population(w)
    # noise_penalty = 0.03 (no shielding park). happiness = 1.0 - 0.03 = 0.97.
    assert w.state.happiness == pytest.approx(0.97)


def test_park_between_industrial_and_house_halves_penalty():
    """Park within chebyshev-2 of both house and source halves noise to -0.015."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="industrial", x=2, y=2, jobs=5)  # cheb=2 to house
    _inject_tile(w, type="park", x=1, y=1)  # cheb=1 to both → shields

    update_population(w)
    # park_benefit = 0.10 (1 park near house). noise = -0.015 (shielded).
    # happiness = 1.0 + 0.10 - 0.015 = 1.085.
    assert w.state.happiness == pytest.approx(1.085)


def test_refinery_also_drops_happiness():
    """Refinery counts as a noise source like industrial."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="refinery", x=2, y=0, jobs=25)  # cheb=2

    update_population(w)
    assert w.state.happiness == pytest.approx(0.97)


def test_noise_averaged_over_multiple_houses():
    """Noise penalty is averaged over all houses, not summed."""
    w = _fresh_world()
    _inject_tile(w, type="house", x=0, y=0, housing_capacity=10)
    _inject_tile(w, type="house", x=10, y=10, housing_capacity=10)  # far away
    _inject_tile(w, type="industrial", x=1, y=1, jobs=5)  # near house 1 only

    update_population(w)
    # House 1: -0.03; House 2: 0. Mean = -0.015. happiness = 0.985.
    assert w.state.happiness == pytest.approx(0.985)


def test_smooth_growth_at_happiness_0_6():
    """PRD §3.3 smooth gate: at happiness=0.6, multiplier = (0.6-0.3)/1.2 = 0.25."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    # Drive happiness to exactly 0.6 via 8h blackout (1.0 - 0.05*8 = 0.6).
    w.state.yesterday_blackout_hours = 8.0
    w.state.population = 400

    update_population(w)

    assert w.state.happiness == pytest.approx(0.6)
    # growth = 0.012 × 400 × 0.25 = 1.2 → +1 → 401.
    assert w.state.population == 401


def test_growth_zero_at_happiness_below_0_3():
    """At happiness < 0.3 the decline branch fires (no growth)."""
    w = _fresh_world()
    _inject_tile(w, type="commercial", x=5, y=5, jobs=1000, housing_capacity=1000)
    # 16h blackout → happiness = 1.0 - 0.05*16 = 0.2 < 0.3.
    w.state.yesterday_blackout_hours = 16.0
    w.state.population = 400

    update_population(w)

    assert w.state.happiness < 0.3
    # decline branch: pop = 400 * 0.99 = 396.
    assert w.state.population == 396


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


def test_sustained_blackout_declines_population_through_step():
    """Integration: a world with insufficient generation runs daily blackouts;
    pop bleeds via the happiness branch within a week. This is the bug from
    issue 22 — without the fix, pop is invariant under continuous blackouts."""
    w = World()
    w.reset(seed=42)
    # Inject abundant capacity + jobs (so pop doesn't decline via housing or
    # job branches), and a high baseline pop. NO power plants → every hour
    # is a blackout.
    w.state.tiles.append(
        Tile(
            id="injected-jobs",
            type="commercial",
            x=5,
            y=5,
            built_day=0,
            operational=True,
            jobs=1000,
            housing_capacity=1000,
        )
    )
    w.state.population = 200
    pop_start = w.state.population

    w.step(days=7)

    # 24 blackout hours/day × 7 days. Happiness pinned at 0 → decline branch.
    assert w.state.population < pop_start
    assert w.state.happiness < 0.5


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


# -- Workforce wiring (slice 02) --------------------------------------------


def _find_tile(w: World, type: str) -> Tile:
    for t in w.state.tiles:
        if t.type == type:
            return t
    raise AssertionError(f"no {type} tile in world")


def test_growth_branch_hires_into_open_vacancies_oldest_first():
    """Growth branch → ``hire_to_fill`` auto-fills the unemployed pool."""
    w = _fresh_world()
    # Pop=200 needed for an integer +1 growth at the new smooth gate
    # (0.012 × 200 × 0.5833 ≈ 1.4 → +1). The injected commercial tile
    # inflates the jobs total so the growth gate (jobs >= pop) passes, but
    # has zero hireable vacancies (catalog spec for commercial caps at 12,
    # so `_spec_jobs - staffed` is negative and hire_to_fill skips it).
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    _inject_tile(w, type="industrial", x=3, y=3, jobs=30, staffed_jobs=0, built_day=2)
    # Commercial is the "inflated jobs" tile: tile.jobs=500 pushes the
    # population growth gate (jobs >= pop) over the line, while staffed_jobs
    # is pinned to its catalog spec (12) so employment math stays sane and
    # hire_to_fill sees no vacancy on this tile.
    _inject_tile(
        w,
        type="commercial",
        x=5,
        y=5,
        jobs=500,
        staffed_jobs=12,
        housing_capacity=300,
        built_day=0,
    )
    w.state.population = 200  # employed = 30 + 30 + 12 = 72, unemployed = 128

    update_population(w)

    # growth = 0.012 × 200 × 0.5833 = 1.4 → +1 → 201.
    assert w.state.population == 201
    older = w.state.tiles[1]
    younger = w.state.tiles[2]
    # Younger (day 2) is the only tile with a hireable vacancy under the
    # catalog spec (30 jobs - 0 staffed). All 30 slots filled, older
    # untouched.
    assert older.staffed_jobs == 30  # day 1, untouched
    assert younger.staffed_jobs == 30  # day 2, filled oldest-first


def test_exodus_branch_fires_newest_when_unemployed_is_zero():
    """capacity < pop → drain via ``drain_n``; with unemployed=0 the newest
    producer loses staff."""
    w = _fresh_world()
    # Shrink town hall housing so capacity drops below pop.
    town_hall = _find_tile(w, "town_hall")
    town_hall.housing_capacity = 50
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    w.state.population = 60  # employed = 30 + 30 = 60, unemployed = 0

    update_population(w)

    # max(50, 60-5) = 55 → delta = 5. All 5 fire newest-first = industrial.
    assert w.state.population == 55
    industrial = w.state.tiles[1]
    assert industrial.staffed_jobs == 25
    assert town_hall.staffed_jobs == 30


def test_exodus_branch_drains_unemployed_first_when_buffer_exists():
    """capacity < pop with unemployed buffer → no producer fires."""
    w = _fresh_world()
    town_hall = _find_tile(w, "town_hall")
    town_hall.housing_capacity = 50
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    _inject_tile(w, type="house", x=4, y=4, housing_capacity=20)
    # employed = 30 + 30 = 60, unemployed = 20, capacity = 50+20 = 70
    w.state.population = 80

    update_population(w)

    # max(70, 80-5) = 75 → delta = 5. All 5 from unemployed; staffing untouched.
    assert w.state.population == 75
    assert town_hall.staffed_jobs == 30
    assert w.state.tiles[1].staffed_jobs == 30


def test_job_decline_branch_drains_unemployed_silently():
    """jobs < 0.7 × pop → drain comes from the unemployed pool."""
    w = _fresh_world()
    # Only the town hall (jobs=30). pop=100. unemployed=70.
    w.state.population = 100

    update_population(w)

    # max(30/0.7=42.86, 99) = 99 → delta = 1. Drained from unemployed.
    assert w.state.population == 99
    town_hall = _find_tile(w, "town_hall")
    assert town_hall.staffed_jobs == 30


def test_happiness_decline_branch_fires_newest_when_unemployed_zero():
    """happiness < 0.3 → drain via ``drain_n``; newest producer loses staff."""
    w = _fresh_world()
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    w.state.population = 60  # employed = 60, unemployed = 0
    # 16h blackout → happiness = 1 - 0.05*16 = 0.2 < 0.3
    w.state.yesterday_blackout_hours = 16.0

    update_population(w)

    assert w.state.happiness < 0.3
    # 60 * 0.99 = 59.4 → 59. delta=1. Newest = industrial.
    assert w.state.population == 59
    industrial = w.state.tiles[1]
    town_hall = _find_tile(w, "town_hall")
    assert industrial.staffed_jobs == 29
    assert town_hall.staffed_jobs == 30


def test_drain_fires_newest_producer_first_with_multiple_young_producers():
    """Fire order respects ``(creation_day, id_string)`` ascending, drained
    in reverse — the youngest producer loses staff first."""
    w = _fresh_world()
    town_hall = _find_tile(w, "town_hall")
    town_hall.housing_capacity = 50  # force exodus
    _inject_tile(w, type="coal_plant", x=2, y=2, jobs=8, built_day=5)
    _inject_tile(w, type="industrial", x=3, y=3, jobs=30, built_day=10)
    _inject_tile(w, type="refinery", x=4, y=4, jobs=25, staffed_jobs=22, built_day=15)
    # employed = 30+8+30+22 = 90, unemployed = 0
    w.state.population = 90

    update_population(w)

    # max(50, 85) = 85 → delta = 5. All 5 come from refinery (newest, day 15).
    assert w.state.population == 85
    refinery = w.state.tiles[3]
    industrial = w.state.tiles[2]
    coal_plant = w.state.tiles[1]
    assert refinery.staffed_jobs == 17
    assert industrial.staffed_jobs == 30  # untouched
    assert coal_plant.staffed_jobs == 8  # untouched
    assert town_hall.staffed_jobs == 30  # untouched


def test_mixed_drain_drains_unemployed_then_fires_newest():
    """Drain order: unemployed pool first, then newest producer."""
    w = _fresh_world()
    town_hall = _find_tile(w, "town_hall")
    town_hall.housing_capacity = 50  # force exodus
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    # employed = 30+30 = 60. population = 65 → unemployed = 5.
    w.state.population = 65

    update_population(w)

    # max(50, 60) = 60 → delta = 5. Take all 5 from unemployed; staffing intact.
    assert w.state.population == 60
    assert w.state.tiles[1].staffed_jobs == 30
    assert town_hall.staffed_jobs == 30

    # Run again: cap still 50, pop=60 → max(50, 55) = 55 → delta=5.
    # Unemployed = 60-60 = 0, so all 5 fire from industrial (newest).
    update_population(w)
    assert w.state.population == 55
    assert w.state.tiles[1].staffed_jobs == 25
    assert town_hall.staffed_jobs == 30


def test_tax_base_uses_post_drain_population_not_employed():
    """Tax = $4 × state.population (post-drain), not $4 × employed."""
    w = _fresh_world()
    town_hall = _find_tile(w, "town_hall")
    town_hall.housing_capacity = 50  # force exodus
    _inject_tile(w, type="industrial", x=2, y=2, jobs=30, built_day=1)
    w.state.population = 100  # employed=60, unemployed=40
    treasury_before = w.state.treasury

    update_population(w)

    # max(50, 95) = 95 → delta=5. Drained from unemployed.
    assert w.state.population == 95
    # Tax = $4 × 95 = $380; NOT $4 × 60 = $240.
    assert w.state.today_summary_so_far["tax_revenue"] == pytest.approx(380.0)
    assert w.state.treasury == pytest.approx(treasury_before + 380.0)


def test_failed_plant_still_drained_by_workforce():
    """Non-operational plants stay in ``producers`` — they can lose workers."""
    w = _fresh_world()
    _inject_tile(w, type="coal_plant", x=2, y=2, jobs=8, built_day=1, operational=False)
    # employed = 30+8 = 38, unemployed = 0
    w.state.population = 38
    w.state.yesterday_blackout_hours = 16.0  # happiness 0.2 < 0.3

    update_population(w)

    # 38 * 0.99 = 37.62 → 37. delta=1.
    # Newest producer is the failed coal plant; it loses 1 worker even
    # though operational=False.
    assert w.state.population == 37
    coal_plant = w.state.tiles[1]
    assert coal_plant.staffed_jobs == 7
    assert coal_plant.operational is False  # unchanged
    town_hall = _find_tile(w, "town_hall")
    assert town_hall.staffed_jobs == 30
