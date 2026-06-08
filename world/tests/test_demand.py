"""Demand model (slice 04, brief §4.3 + PRD's split-scope event multipliers).

The PRD overrides the brief's bottom-line `× heatwave × demand_surprise`:

  * Heatwave (1.40) multiplies *residential demand only*.
  * Demand surprise (1.30) multiplies *commercial + industrial only*.
  * Process loads always pass through.

Tests force events on by injecting entries directly into
`state.active_events`, since the event-sampling pipeline doesn't fire
until slice 11.
"""

from __future__ import annotations

import pytest

from world.event_effects import (
    DEMAND_SURPRISE_IC_MULT,
    HEATWAVE_RESIDENTIAL_MULT,
    demand_surprise_ic_mult,
    heatwave_residential_mult,
)
from world.power import (
    PER_CAPITA_KW,
    commercial_factor,
    hourly_factor,
    residential_kw,
    seasonal_demand_factor,
    total_demand_kw,
)
from world.sim import World
from world.state import Tile


def _fresh_world() -> World:
    w = World()
    w.reset(seed=42)
    return w


def _inject_tile(
    w: World, *, tile_type: str, x: int, y: int, staffed_jobs: int | None = None
) -> None:
    """Bypass /build to plant a demand-bearing tile directly.

    Workforce slice 01: defaults ``staffed_jobs`` to ``spec.jobs`` so injected
    producer tiles look fully staffed by the helper. Slice 05 tests that want
    partial / idle staffing pass ``staffed_jobs=N`` explicitly.
    """
    from world.catalog import TILE_CATALOG

    spec = TILE_CATALOG[tile_type]
    w.state.tiles.append(
        Tile(
            id=f"injected-{tile_type}-{x}-{y}",
            type=tile_type,
            x=x,
            y=y,
            built_day=0,
            operational=True,
            housing_capacity=spec.housing_capacity,
            jobs=spec.jobs,
            demand_kw=spec.demand_kw,
            staffed_jobs=spec.jobs if staffed_jobs is None else staffed_jobs,
        )
    )


# -- Hourly factor buckets ---------------------------------------------------


def test_hourly_factor_peaks_at_midday_with_evening_shoulder() -> None:
    """Daytime-peaked shape: max at h=12, evening shoulder, night trough.

    Replaces the brief's stepped curve; intra-day mix shifts toward
    daytime while the daily total stays pinned (see
    `test_hourly_factor_daily_total_is_preserved`).
    """
    # Midday is the unique peak.
    assert hourly_factor(12) == 1.50
    for h in range(24):
        if h != 12:
            assert hourly_factor(h) < hourly_factor(12)

    # Evening shoulder (17-19) sits well above night but below midday.
    for h in (17, 18, 19):
        assert 1.0 < hourly_factor(h) < hourly_factor(12)

    # Night trough (h=1-3) is the lowest band.
    for h in (1, 2, 3):
        assert hourly_factor(h) == 0.35
    # And every other hour is at least as high as the trough.
    for h in range(24):
        assert hourly_factor(h) >= 0.35

    # Daytime hours all clear the night floor by a wide margin.
    for h in range(9, 17):
        assert hourly_factor(h) >= 1.20


def test_hourly_factor_daily_total_is_preserved() -> None:
    """24-hour sum stays at 22.3 (≈ the brief's stepped curve's sum).

    City-level economics are tuned against this total; the
    `improve-codebase-architecture`-driven reshape is intra-day only.
    """
    total = sum(hourly_factor(h) for h in range(24))
    assert total == pytest.approx(22.30)


def test_residential_kw_zero_when_pop_zero() -> None:
    assert residential_kw(12, pop=0) == 0.0


def test_residential_kw_midday_peak() -> None:
    # pop=100, h=12 (midday peak) → 100 * 0.333 * 1.5 = 49.95
    assert residential_kw(12, pop=100) == pytest.approx(100 * PER_CAPITA_KW * 1.50)


# -- Commercial factor -------------------------------------------------------


def test_commercial_factor_full_during_business_hours() -> None:
    for h in range(8, 20):
        assert commercial_factor(h) == 1.0


def test_commercial_factor_quiet_off_hours() -> None:
    for h in (0, 7, 20, 23):
        assert commercial_factor(h) == 0.2


# -- Industrial passes through unchanged -------------------------------------


def test_industrial_continuous_demand() -> None:
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5)
    # Drop population so residential is zero; isolate the industrial term.
    w.state.population = 0
    # 300 kW continuous; sample several hours.
    for h in (0, 6, 12, 18, 23):
        assert total_demand_kw(w.state, h) == pytest.approx(300.0)


def test_commercial_demand_swings_with_factor() -> None:
    w = _fresh_world()
    _inject_tile(w, tile_type="commercial", x=5, y=5)
    w.state.population = 0
    # 50 kW peak during 8-19h; 10 kW (20%) otherwise.
    assert total_demand_kw(w.state, 12) == pytest.approx(50.0)
    assert total_demand_kw(w.state, 0) == pytest.approx(10.0)


# -- Workforce efficiency scales civilian demand (slice 05) -----------------


def test_idle_commercial_draws_zero_demand() -> None:
    """staffed_jobs=0 → efficiency=0 → no commercial contribution at any hour."""
    w = _fresh_world()
    _inject_tile(w, tile_type="commercial", x=5, y=5, staffed_jobs=0)
    w.state.population = 0
    for h in range(24):
        assert total_demand_kw(w.state, h) == pytest.approx(0.0)


def test_half_staffed_commercial_draws_half_peak() -> None:
    """jobs=12 staffed=6 → efficiency=0.5 → 25 kW peak / 5 kW off-peak."""
    w = _fresh_world()
    _inject_tile(w, tile_type="commercial", x=5, y=5, staffed_jobs=6)
    w.state.population = 0
    # h=12 → commercial_factor=1.0 → 50 × 0.5 × 1.0 = 25 kW.
    assert total_demand_kw(w.state, 12) == pytest.approx(25.0)
    # h=22 → commercial_factor=0.2 → 50 × 0.5 × 0.2 = 5 kW.
    assert total_demand_kw(w.state, 22) == pytest.approx(5.0)


def test_idle_industrial_draws_zero_demand() -> None:
    """staffed_jobs=0 → industrial drops out of total_demand_kw entirely."""
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5, staffed_jobs=0)
    w.state.population = 0
    for h in (0, 6, 12, 18, 23):
        assert total_demand_kw(w.state, h) == pytest.approx(0.0)


def test_half_staffed_industrial_draws_half() -> None:
    """jobs=30 staffed=15 → efficiency=0.5 → 150 kW continuous."""
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5, staffed_jobs=15)
    w.state.population = 0
    for h in (0, 6, 12, 18, 23):
        assert total_demand_kw(w.state, h) == pytest.approx(150.0)


# -- Event multipliers (PRD split scope) -------------------------------------


def test_no_events_means_unit_multipliers() -> None:
    w = _fresh_world()
    assert heatwave_residential_mult(w.state) == 1.0
    assert demand_surprise_ic_mult(w.state) == 1.0


def test_heatwave_multiplies_residential_only() -> None:
    """Heatwave × 1.4 applies to residential demand and nothing else."""
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5)
    _inject_tile(w, tile_type="commercial", x=6, y=6)
    w.state.population = 100

    h = 12  # midday
    base_residential = residential_kw(h, w.state.population)
    seasonal = seasonal_demand_factor(w.state.day)
    base_industrial = 300.0
    base_commercial = 50.0  # full during 8-20h
    expected_no_event = base_residential * seasonal + base_industrial + base_commercial
    assert total_demand_kw(w.state, h) == pytest.approx(expected_no_event)

    w.state.active_events = [{"type": "heatwave", "days_left": 5}]
    expected_heatwave = (
        base_residential * seasonal * HEATWAVE_RESIDENTIAL_MULT + base_industrial + base_commercial
    )
    assert total_demand_kw(w.state, h) == pytest.approx(expected_heatwave)
    # Industrial + commercial untouched: difference == residential * seasonal * 0.4.
    assert total_demand_kw(w.state, h) - expected_no_event == pytest.approx(
        base_residential * seasonal * (HEATWAVE_RESIDENTIAL_MULT - 1.0)
    )


def test_demand_surprise_multiplies_industrial_and_commercial_only() -> None:
    """Demand surprise × 1.3 applies to I+C only, leaving residential alone."""
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5)
    _inject_tile(w, tile_type="commercial", x=6, y=6)
    w.state.population = 100

    h = 14  # business hours
    seasonal = seasonal_demand_factor(w.state.day)
    base_residential = residential_kw(h, w.state.population) * seasonal
    base_ic = 300.0 + 50.0
    expected_no_event = base_residential + base_ic
    assert total_demand_kw(w.state, h) == pytest.approx(expected_no_event)

    w.state.active_events = [{"type": "demand_surprise", "days_left": 10}]
    expected = base_residential + base_ic * DEMAND_SURPRISE_IC_MULT
    assert total_demand_kw(w.state, h) == pytest.approx(expected)
    # Residential untouched by demand_surprise.
    assert total_demand_kw(w.state, h) - expected_no_event == pytest.approx(
        base_ic * (DEMAND_SURPRISE_IC_MULT - 1.0)
    )


def test_both_multipliers_compose_on_their_own_scopes() -> None:
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5)
    _inject_tile(w, tile_type="commercial", x=6, y=6)
    w.state.population = 100
    w.state.active_events = [
        {"type": "heatwave", "days_left": 5},
        {"type": "demand_surprise", "days_left": 10},
    ]

    h = 14
    expected = (
        residential_kw(h, w.state.population)
        * seasonal_demand_factor(w.state.day)
        * HEATWAVE_RESIDENTIAL_MULT
        + (300.0 + 50.0) * DEMAND_SURPRISE_IC_MULT
    )
    assert total_demand_kw(w.state, h) == pytest.approx(expected)


# -- Seasonal demand factor --------------------------------------------------


def test_seasonal_demand_factor_peaks_in_january_troughs_in_july() -> None:
    peak = seasonal_demand_factor(15)   # Jan 15
    trough = seasonal_demand_factor(196)  # Jul 15
    assert peak == pytest.approx(1.40, abs=0.02)
    assert trough == pytest.approx(0.60, abs=0.02)


def test_seasonal_demand_factor_range() -> None:
    all_days = [seasonal_demand_factor(D) for D in range(365)]
    assert min(all_days) >= 0.59
    assert max(all_days) <= 1.41


def test_seasonal_demand_applies_to_residential_not_ic() -> None:
    """Seasonal factor only scales residential; I+C are unaffected."""
    w = _fresh_world()
    _inject_tile(w, tile_type="industrial", x=5, y=5)
    w.state.population = 0  # zero out residential

    h = 12
    base_industrial = total_demand_kw(w.state, h)

    # Force summer (low seasonal factor) vs winter (high seasonal factor).
    w.state.day = 196  # July 15 — seasonal factor ≈ 0.60
    summer_demand = total_demand_kw(w.state, h)
    w.state.day = 15  # Jan 15 — seasonal factor ≈ 1.40
    winter_demand = total_demand_kw(w.state, h)

    # With pop=0 there is no residential component, so season must not change demand.
    assert summer_demand == pytest.approx(base_industrial)
    assert winter_demand == pytest.approx(base_industrial)


# -- Sim integration ---------------------------------------------------------


def test_state_power_now_demand_populated_after_step() -> None:
    w = _fresh_world()
    w.step(days=1)
    # Demand at hour 23 (the last hour simulated of day 0): factor 0.7,
    # only town hall standing → no industrial/commercial demand. Pop changed
    # from 100 → 99 by end-of-day population update. Whatever the exact
    # value, it must be a non-negative finite float.
    val = w.state.power_now.demand_kw
    assert isinstance(val, float)
    assert val >= 0.0


def test_demand_includes_population_and_tiles() -> None:
    """A 1-industrial world's demand must exceed a 0-tile world's demand."""
    bare = _fresh_world()
    bare.step(days=1)
    bare_demand = bare.state.power_now.demand_kw

    big = _fresh_world()
    _inject_tile(big, tile_type="industrial", x=5, y=5)
    big.step(days=1)

    assert big.state.power_now.demand_kw > bare_demand + 200.0  # +300kW continuous
