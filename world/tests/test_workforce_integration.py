"""Workforce integration tests (slice 01).

Drives build/drill/demolish through `World` and asserts the `/state`-shaped
read model (employed/unemployed totals + per-tile/per-well staffed_jobs).
"""

from __future__ import annotations

from world.catalog import TILE_CATALOG
from world.sim import World


def _hc_voxel(w: World):
    return next(iter(w.subsurface.voxels.values()))


def test_day_zero_town_hall_is_fully_staffed() -> None:
    w = World()
    w.reset(seed=42)
    state = w.state_dict()
    assert state["employed"] == 30
    assert state["unemployed"] == 70
    th = next(t for t in state["tiles"] if t["type"] == "town_hall")
    assert th["staffed_jobs"] == 30
    assert th["jobs"] == 30


def test_build_coal_plant_with_available_labor_staffs_to_full() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 1_000_000.0
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    res = w.build("coal_plant", th.x + 1, th.y)
    assert res["ok"] is True
    state = w.state_dict()
    coal = next(t for t in state["tiles"] if t["type"] == "coal_plant")
    assert coal["staffed_jobs"] == 30
    # unemployed dropped by 30 (70 → 40).
    assert state["unemployed"] == 40
    assert state["employed"] == 60


def test_build_coal_plant_with_partial_labor_staffs_to_pool_size() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 1_000_000.0
    # Drain pool to 5: pop=100, town hall employs 30. Drop pop to 35 → 5 idle.
    w.state.population = 35
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    res = w.build("coal_plant", th.x + 1, th.y)
    assert res["ok"] is True
    state = w.state_dict()
    coal = next(t for t in state["tiles"] if t["type"] == "coal_plant")
    assert coal["staffed_jobs"] == 5
    assert state["unemployed"] == 0


def test_build_coal_plant_with_zero_labor_is_unstaffed() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 1_000_000.0
    w.state.population = 30  # exactly fills town hall; 0 unemployed
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    res = w.build("coal_plant", th.x + 1, th.y)
    assert res["ok"] is True
    coal = next(t for t in w.state.tiles if t.type == "coal_plant")
    assert coal.staffed_jobs == 0


def test_drill_oil_well_with_available_labor_staffs_to_full() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 1_000_000.0
    hc = _hc_voxel(w)
    res = w.drill(hc.x, hc.y, hc.z, "production")
    assert res["ok"] is True
    state = w.state_dict()
    well = next(wd for wd in state["wells"] if wd["type"] == "production")
    assert well["staffed_jobs"] == 3
    assert state["employed"] == 30 + 3


def test_demolish_returns_workers_and_backfills_older_facility() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 5_000_000.0
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    # Build a refinery and an industrial both adjacent to the town hall (town
    # hall counts as road for adjacency). Refinery is built first → older.
    w.build("refinery", th.x + 1, th.y)
    w.build("industrial", th.x, th.y + 1)
    rf = next(t for t in w.state.tiles if t.type == "refinery")
    ind = next(t for t in w.state.tiles if t.type == "industrial")
    # Pin a scenario: refinery under-staffed (20/25), industrial fully staffed
    # (30/30), town hall full (30/30). Population matches employed exactly so
    # the unemployed pool is empty and the demolish-backfill is observable.
    rf.staffed_jobs = 20
    ind.staffed_jobs = 30
    w.state.population = 30 + 20 + 30  # 80
    # Demolish industrial — its 30 workers return to the pool, refinery (older)
    # backfills 5 vacancies, leaving 25 unemployed.
    res = w.demolish(ind.x, ind.y)
    assert res["ok"] is True
    assert rf.staffed_jobs == 25
    state = w.state_dict()
    assert state["unemployed"] == 25
    assert state["employed"] == 55


def test_state_surface_has_employed_and_unemployed_top_level() -> None:
    w = World()
    w.reset(seed=42)
    state = w.state_dict()
    assert "employed" in state
    assert "unemployed" in state
    assert state["employed"] + state["unemployed"] == state["population"]


def test_state_tiles_and_wells_carry_staffed_jobs() -> None:
    w = World()
    w.reset(seed=42)
    w.state.treasury = 1_000_000.0
    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    state = w.state_dict()
    for entry in state["tiles"]:
        assert "staffed_jobs" in entry
    for entry in state["wells"]:
        assert "staffed_jobs" in entry


def test_catalog_exposes_jobs_for_plants_and_wells() -> None:
    expectations = {
        "coal_plant": 30,
        "gas_peaker": 4,
        "solar_farm": 2,
        "wind_turbine": 2,
        "oil_well": 3,
        "injection_well": 2,
    }
    for tile_type, expected in expectations.items():
        assert TILE_CATALOG[tile_type].jobs == expected
