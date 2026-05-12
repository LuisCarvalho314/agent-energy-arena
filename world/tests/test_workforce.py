"""Workforce module (slice 01) — pure-function unit tests.

Exercises `world/workforce.py` directly: ordering, hire allocator, drain
allocator, and `efficiency` boundary cases.
"""

from __future__ import annotations

from world.catalog import TILE_CATALOG
from world.sim import World
from world.state import Tile, Well
from world.workforce import (
    drain_n,
    efficiency,
    employed,
    hire_to_fill,
    producers,
    unemployed,
)


def _fresh_world() -> World:
    w = World()
    w.reset(seed=42)
    return w


def _inject_tile(
    w: World,
    *,
    tile_type: str,
    x: int,
    y: int,
    built_day: int = 0,
    staffed_jobs: int | None = None,
    tid: str | None = None,
) -> Tile:
    spec = TILE_CATALOG[tile_type]
    tile = Tile(
        id=tid or f"injected-{tile_type}-{x}-{y}",
        type=tile_type,
        x=x,
        y=y,
        built_day=built_day,
        operational=True,
        housing_capacity=spec.housing_capacity,
        jobs=spec.jobs,
        staffed_jobs=spec.jobs if staffed_jobs is None else staffed_jobs,
    )
    w.state.tiles.append(tile)
    return tile


def _inject_well(
    w: World,
    *,
    well_type: str,
    x: int,
    y: int,
    drilled_day: int = 0,
    staffed_jobs: int | None = None,
    wid: str | None = None,
) -> Well:
    spec_type = "oil_well" if well_type == "production" else "injection_well"
    spec = TILE_CATALOG[spec_type]
    well = Well(
        id=wid or f"injected-{well_type}-{x}-{y}",
        type=well_type,
        x=x,
        y=y,
        target_z=0,
        drilled_day=drilled_day,
        staffed_jobs=spec.jobs if staffed_jobs is None else staffed_jobs,
    )
    w.state.wells.append(well)
    return well


# -- efficiency boundary cases ----------------------------------------------


def test_efficiency_passive_tile_returns_one() -> None:
    t = Tile(id="r-1", type="road", x=0, y=0, built_day=0)
    assert efficiency(t) == 1.0


def test_efficiency_zero_staff_returns_zero() -> None:
    t = Tile(id="c-1", type="coal_plant", x=0, y=0, built_day=0, jobs=8, staffed_jobs=0)
    assert efficiency(t) == 0.0


def test_efficiency_full_staff_returns_one() -> None:
    t = Tile(id="c-1", type="coal_plant", x=0, y=0, built_day=0, jobs=8, staffed_jobs=8)
    assert efficiency(t) == 1.0


def test_efficiency_partial_returns_ratio() -> None:
    t = Tile(id="c-1", type="coal_plant", x=0, y=0, built_day=0, jobs=8, staffed_jobs=4)
    assert efficiency(t) == 0.5


# -- producers ordering ------------------------------------------------------


def test_producers_orders_by_creation_day_then_id() -> None:
    w = _fresh_world()
    # Drop the auto-placed town hall so we can sequence ids ourselves.
    w.state.tiles.clear()
    # day 0 — town hall (a-prefix id wins tiebreak)
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, tid="a-town")
    # day 1 — oil well
    ow = _inject_well(w, well_type="production", x=1, y=0, drilled_day=1, wid="b-oil")
    # day 2 — coal plant, then injection well with later id
    cp = _inject_tile(w, tile_type="coal_plant", x=2, y=0, built_day=2, tid="c-coal")
    iw = _inject_well(w, well_type="injection", x=3, y=0, drilled_day=2, wid="d-inj")
    assert list(producers(w.state)) == [th, ow, cp, iw]


def test_producers_excludes_passive_tiles() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    _inject_tile(w, tile_type="road", x=0, y=0)
    _inject_tile(w, tile_type="house", x=0, y=1)
    industrial = _inject_tile(w, tile_type="industrial", x=0, y=2)
    assert list(producers(w.state)) == [industrial]


# -- hire_to_fill ------------------------------------------------------------


def test_hire_to_fill_oldest_first_pool_short_of_first_facility() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, staffed_jobs=0, tid="a-th")
    rf = _inject_tile(w, tile_type="refinery", x=1, y=0, built_day=1, staffed_jobs=0, tid="b-rf")
    w.state.population = 10
    hire_to_fill(w.state)
    assert th.staffed_jobs == 10
    assert rf.staffed_jobs == 0
    assert unemployed(w.state) == 0
    assert employed(w.state) == 10


def test_hire_to_fill_fills_oldest_then_spills_to_next() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, staffed_jobs=0, tid="a-th")
    ind = _inject_tile(
        w, tile_type="industrial", x=1, y=0, built_day=1, staffed_jobs=0, tid="b-ind"
    )
    w.state.population = 40
    hire_to_fill(w.state)
    assert th.staffed_jobs == 30
    assert ind.staffed_jobs == 10
    assert unemployed(w.state) == 0


def test_hire_to_fill_idempotent_when_pool_empty() -> None:
    w = _fresh_world()
    # Fresh reset has town_hall=30/30, pop=100. Run hire_to_fill again — no
    # producer to hire into, employed unchanged.
    before = employed(w.state)
    hire_to_fill(w.state)
    assert employed(w.state) == before


# -- drain_n -----------------------------------------------------------------


def test_drain_n_unemployed_first_keeps_workers() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, staffed_jobs=30, tid="a-th")
    w.state.population = 100  # 30 employed, 70 unemployed
    drain_n(w.state, 50)
    assert w.state.population == 50
    assert th.staffed_jobs == 30


def test_drain_n_falls_through_to_newest_first_fire() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, staffed_jobs=30, tid="a-th")
    _inject_tile(w, tile_type="industrial", x=1, y=0, built_day=1, staffed_jobs=0, tid="b-ind")
    w.state.population = 30  # unemployed=0; only the town hall has staff
    drain_n(w.state, 5)
    assert th.staffed_jobs == 25
    assert w.state.population == 25


def test_drain_n_fires_newest_first() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    th = _inject_tile(w, tile_type="town_hall", x=0, y=0, built_day=0, staffed_jobs=30, tid="a-th")
    ind = _inject_tile(
        w, tile_type="industrial", x=1, y=0, built_day=1, staffed_jobs=30, tid="b-ind"
    )
    w.state.population = 60  # unemployed=0
    drain_n(w.state, 10)
    assert ind.staffed_jobs == 20
    assert th.staffed_jobs == 30
    assert w.state.population == 50


def test_unemployed_clamps_at_zero_when_employed_exceeds_pop() -> None:
    w = _fresh_world()
    w.state.tiles.clear()
    _inject_tile(w, tile_type="industrial", x=0, y=0, built_day=0, staffed_jobs=30, tid="a-ind")
    w.state.population = 5
    assert unemployed(w.state) == 0


# -- well jobs ---------------------------------------------------------------


def test_efficiency_handles_wells() -> None:
    w_full = Well(
        id="w-1",
        type="production",
        x=0,
        y=0,
        target_z=0,
        drilled_day=0,
        staffed_jobs=3,
    )
    w_half = Well(
        id="w-2",
        type="injection",
        x=1,
        y=0,
        target_z=0,
        drilled_day=0,
        staffed_jobs=1,
    )
    assert efficiency(w_full) == 1.0
    assert efficiency(w_half) == 0.5
