"""Determinism invariants for the simulation foundation."""

from __future__ import annotations

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


def test_step_clamps_days_range():
    """`days` must be in [1, 7]."""
    import pytest

    w = World()
    w.reset(seed=42)
    with pytest.raises(ValueError):
        w.step(days=0)
    with pytest.raises(ValueError):
        w.step(days=8)
