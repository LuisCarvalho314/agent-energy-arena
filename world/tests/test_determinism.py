"""Determinism invariants for the simulation foundation."""

from __future__ import annotations

from dataclasses import asdict

from world.sim import World


def test_same_seed_reproduces_state():
    a = World()
    b = World()
    a.reset(seed=42)
    b.reset(seed=42)
    for _ in range(2):
        a.step(days=5)
        b.step(days=5)
    assert a.day == b.day
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()


def test_step_size_invariance():
    """step(days=7) is byte-identical to step(days=1) called 7 times."""
    a = World()
    b = World()
    a.reset(seed=42)
    b.reset(seed=42)

    a.step(days=7)
    for _ in range(7):
        b.step(days=1)

    assert a.day == b.day == 7
    # Identical RNG state: next draws must match.
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()


def test_step_size_invariance_mixed():
    """step(3) + step(4) ≡ step(7)."""
    a = World()
    b = World()
    a.reset(seed=42)
    b.reset(seed=42)

    a.step(days=7)
    b.step(days=3)
    b.step(days=4)

    assert a.day == b.day == 7
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()


def test_forecast_does_not_perturb_sim_rng():
    """Calling forecast draws from forecast_rng only; sim_rng is untouched."""
    w = World()
    w.reset(seed=42)
    w.step(days=3)

    # Capture the next sim_rng draw before any forecast calls.
    snapshot = World()
    snapshot.reset(seed=42)
    snapshot.step(days=3)
    expected_next = snapshot.sim_rng.standard_normal()

    # Pound the forecast endpoint.
    for _ in range(50):
        w.forecast(hours=24)

    assert w.sim_rng.standard_normal() == expected_next


def test_reset_reseeds_both_streams():
    w = World()
    w.reset(seed=42)
    w.step(days=5)
    w.forecast(hours=24)

    fresh = World()
    fresh.reset(seed=42)

    w.reset(seed=42)
    assert w.day == 0
    assert w.sim_rng.standard_normal() == fresh.sim_rng.standard_normal()
    assert w.forecast_rng.standard_normal() == fresh.forecast_rng.standard_normal()


def test_action_sequence_byte_identical():
    """Two `reset(seed=42)` worlds + identical action sequence produce
    byte-identical state.tiles, state.wells (with `reservoir_id`),
    subsurface voxels (with `reservoir_id`), treasury, and population.

    oilfield-v2 issue 10 AC: pin the contract that the scripted-agent
    baseline rests on — any rogue RNG draw or order-dependent dict
    iteration in the build/drill/survey/step path would diverge here.
    """

    def _play() -> World:
        w = World()
        w.reset(seed=42)
        # Mix every mutating endpoint a scripted agent uses: build (road
        # + civilian + plant + pipeline + refinery), survey, drill,
        # control, demolish, then step. The action ordering exercises
        # the same code paths as the scripted baseline run.
        w.build("road", 16, 17)
        w.build("road", 16, 18)
        w.build("house", 17, 17)
        w.build("commercial", 17, 18)
        w.build("solar_farm", 24, 24)
        w.build("pipeline", 5, 5)
        w.survey(8, 8, 4)
        # Drill at the surveyed column's center voxel — z picked from
        # the brief's mid-depth so the call is well-formed regardless
        # of seed-specific HC placement (drill returns ok even when
        # the voxel is rock, just yields zero production).
        w.drill(8, 8, 5, "production")
        # Stacked completion (reservoir-scale-and-stacked-completions #07):
        # second producer at same (x, y) with |Δz| ≥ 3 is now legal under
        # the relaxed §4.12 rule. Pinning byte-identity across the stack
        # ensures the drill order and reservoir-id assignment for the
        # second completion are deterministic.
        w.drill(8, 8, 9, "production")
        w.step(days=7)
        return w

    a = _play()
    b = _play()

    assert a.state.treasury == b.state.treasury
    assert a.state.population == b.state.population
    assert [asdict(t) for t in a.state.tiles] == [asdict(t) for t in b.state.tiles]
    assert [asdict(w) for w in a.state.wells] == [asdict(w) for w in b.state.wells]
    # reservoir_id is on Well — pinned by the dict-equality above. Subsurface
    # voxels carry their own reservoir_id; compare the sparse store directly.
    a_vox = {k: asdict(v) for k, v in a.subsurface.voxels.items()}
    b_vox = {k: asdict(v) for k, v in b.subsurface.voxels.items()}
    assert a_vox == b_vox


def test_seed_42_post_upgrade_replay_byte_identical():
    """balance-upgrade-p0 #06: pin byte-identical replay on seed 42 after the
    upgrade lands (battery dispatch, coal rebalance + per-fuel shock, spatial
    happiness, heatwave solar derate).

    A judge replaying the eval-seed run end-to-end must observe the same
    final treasury, population, tile state (including new battery fields
    `soc_kwh` and `charge_setpoint_kw`), active_events sequence, and
    cumulative renewable-share counters. Two same-seed worlds running the
    same scripted-style action sequence (build solar + battery, set a
    manual charge setpoint, step a long stretch so dispatch + events have
    a chance to fire) must agree byte-for-byte.

    Distinct from `test_action_sequence_byte_identical` (which pre-dates
    the upgrade and focuses on build/survey/drill); this test specifically
    pins the post-upgrade contract: battery state survives `step()`,
    event roll cadence is unchanged, and the new per-fuel shock + spatial
    happiness paths are byte-stable on seed 42.
    """

    def _play() -> World:
        w = World()
        w.reset(seed=42)
        th = next(t for t in w.state.tiles if t.type == "town_hall")
        # Exercise the new post-upgrade code paths: a battery sitting next
        # to renewable supply with a non-zero manual setpoint, plus a coal
        # plant so the per-fuel shock branch is touchable by the events
        # roll, plus residential/industrial so spatial happiness has
        # something to evaluate.
        w.build("road", th.x + 1, th.y)
        w.build("road", th.x + 2, th.y)
        # Extend the road chain south so the coal plant at th.x + 5, th.y
        # has orthogonal road adjacency without colliding with the
        # solar/battery/coal cells.
        w.build("road", th.x + 2, th.y - 1)
        w.build("road", th.x + 3, th.y - 1)
        w.build("road", th.x + 4, th.y - 1)
        w.build("road", th.x + 5, th.y - 1)
        w.build("house", th.x + 1, th.y + 1)
        w.build("industrial", th.x + 2, th.y + 1)
        w.build("solar_farm", th.x + 3, th.y)
        w.build("battery", th.x + 4, th.y)
        w.build("coal_plant", th.x + 5, th.y)
        battery = next(t for t in w.state.tiles if t.type == "battery")
        # Negative setpoint exercises the discharge-only manual branch in
        # `battery_discharge_step`; the value is preserved across step().
        w.control_battery(battery.id, charge_kw=-50.0)
        # Long enough to give the events RNG room to draw (heatwave +
        # fuel shock at ~0.006/day each, plus the per-plant failure roll
        # cadence) and to accumulate measurable renewable-share kwh.
        w.step(days=7)
        w.step(days=7)
        return w

    a = _play()
    b = _play()

    # Core balance + headline state.
    assert a.state.treasury == b.state.treasury
    assert a.state.population == b.state.population

    # Battery fields land on Tile (issue 01 contract: soc_kwh +
    # charge_setpoint_kw survive step()). Pinned by full dict-equality.
    a_tiles = [asdict(t) for t in a.state.tiles]
    b_tiles = [asdict(t) for t in b.state.tiles]
    assert a_tiles == b_tiles

    # Renewable-share accumulators (issue 02 contract: battery discharge
    # counts in numerator and denominator).
    assert a.state.cumulative_total_served_kwh == b.state.cumulative_total_served_kwh
    assert a.state.cumulative_renewable_served_kwh == b.state.cumulative_renewable_served_kwh

    # Event sequence (issue 03 contract: per-plant roll cadence is
    # unchanged — only the per-type threshold moves).
    assert a.state.active_events == b.state.active_events
    assert a.state.historical_events == b.state.historical_events

    # Carbon price + regulatory tightenings are downstream of the same
    # RNG stream; pinning here guards against silent drift in the
    # tightening counter on seed 42.
    assert a.state.carbon_price == b.state.carbon_price
    assert a.state.regulatory_tightenings_applied == b.state.regulatory_tightenings_applied

    # RNG state must match for any subsequent draw.
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()


def test_step_clamps_days_range():
    """`days` must be in [1, 7]."""
    import pytest

    w = World()
    w.reset(seed=42)
    with pytest.raises(ValueError):
        w.step(days=0)
    with pytest.raises(ValueError):
        w.step(days=8)
