"""Quadratic-in-depth drilling cost (oilfield-v2 slice 05).

`drill_capex(base, target_z, world_d) = base * (1 + (target_z / world_d) ** 2)`
applies to both production and injection wells with their own per-well-type
bases. The catalog exposes `cost_formula` + `world_depth` so UI / agent clients
can replicate the math without re-implementing the helper.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from world.api import create_app
from world.catalog import TILE_CATALOG, build_catalog
from world.sim import World
from world.subsurface import drill_capex

# -- Pure helper ------------------------------------------------------------


def test_drill_capex_at_z_zero_returns_base() -> None:
    assert drill_capex(50_000.0, 0, 16) == 50_000.0
    assert drill_capex(30_000.0, 0, 16) == 30_000.0


def test_drill_capex_at_max_z_returns_base_times_one_plus_ratio_squared() -> None:
    world_d = 16
    z = world_d - 1
    expected_prod = 50_000.0 * (1.0 + (z / world_d) ** 2)
    expected_inj = 30_000.0 * (1.0 + (z / world_d) ** 2)
    assert drill_capex(50_000.0, z, world_d) == expected_prod
    assert drill_capex(30_000.0, z, world_d) == expected_inj


def test_drill_capex_monotonic_in_target_z() -> None:
    base = 50_000.0
    world_d = 16
    values = [drill_capex(base, z, world_d) for z in range(world_d)]
    assert values == sorted(values)
    # Strict increase past z=0.
    for prev, nxt in zip(values, values[1:], strict=False):
        assert nxt > prev


def test_drill_capex_formula_applies_to_both_well_bases() -> None:
    """The helper takes `base` as a parameter so it is agnostic to well type.
    Pin that the production-well and injection-well static catalog bases (50k
    / 30k) both flow through the formula correctly at a non-trivial depth."""
    target_z = 8
    world_d = 16
    oil_base = TILE_CATALOG["oil_well"].capex
    inj_base = TILE_CATALOG["injection_well"].capex
    assert drill_capex(oil_base, target_z, world_d) == oil_base * 1.25
    assert drill_capex(inj_base, target_z, world_d) == inj_base * 1.25


# -- /drill treasury debit -------------------------------------------------


def test_drill_production_treasury_debit_matches_helper_at_target_z() -> None:
    w = World()
    w.reset(seed=42)
    target_z = 8
    before = w.state.treasury
    res = w.drill(10, 10, target_z, "production")
    assert res["ok"] is True
    expected = drill_capex(50_000.0, target_z, w.config.world_d)
    assert before - w.state.treasury == expected
    # Snapshot-on-build: Well.capex_paid carries the depth-scaled value.
    assert w.state.wells[0].capex_paid == expected


def test_drill_injection_treasury_debit_matches_helper_at_target_z() -> None:
    w = World()
    w.reset(seed=42)
    target_z = 12
    before = w.state.treasury
    res = w.drill(10, 10, target_z, "injection")
    assert res["ok"] is True
    expected = drill_capex(30_000.0, target_z, w.config.world_d)
    assert before - w.state.treasury == expected
    assert w.state.wells[0].capex_paid == expected


def test_drill_at_z_zero_costs_base_only() -> None:
    w = World()
    w.reset(seed=42)
    before = w.state.treasury
    w.drill(10, 10, 0, "production")
    assert before - w.state.treasury == 50_000.0


def test_drill_at_deepest_z_costs_more_than_at_shallow_z() -> None:
    """Two side-by-side drills at different depths produce different debits."""
    w = World()
    w.reset(seed=42)
    t0 = w.state.treasury
    w.drill(10, 10, 1, "production")
    debit_shallow = t0 - w.state.treasury
    t1 = w.state.treasury
    w.drill(11, 10, 15, "production")
    debit_deep = t1 - w.state.treasury
    assert debit_deep > debit_shallow


# -- /catalog exposure -----------------------------------------------------


def test_catalog_drill_production_exposes_cost_formula_and_world_depth() -> None:
    cat = build_catalog()
    prod = cat["subsurface"]["drill"]["production"]
    assert prod["cost_formula"] == "base * (1 + (target_z / world_depth)**2)"
    assert isinstance(prod["world_depth"], int)
    assert prod["world_depth"] >= 1
    # Base unchanged from prior slices.
    assert prod["capex"] == 50_000


def test_catalog_drill_injection_exposes_cost_formula_and_world_depth() -> None:
    cat = build_catalog()
    inj = cat["subsurface"]["drill"]["injection"]
    assert inj["cost_formula"] == "base * (1 + (target_z / world_depth)**2)"
    assert isinstance(inj["world_depth"], int)
    assert inj["world_depth"] >= 1
    assert inj["capex"] == 30_000


def test_catalog_world_depth_matches_world_config() -> None:
    """Catalog world_depth must equal the running world's `config.world_d` so
    clients computing the per-z cost match what /drill actually charges."""
    w = World()
    w.reset(seed=42)
    client = TestClient(create_app(world=w))
    cat = client.get("/catalog").json()
    assert cat["subsurface"]["drill"]["production"]["world_depth"] == w.config.world_d
    assert cat["subsurface"]["drill"]["injection"]["world_depth"] == w.config.world_d
