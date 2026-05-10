"""Refinery + crude routing (slice 09, brief §4.6).

Covers the refining yield (0.85), crude routing priority (descending
setpoint, id-ascending tiebreak), single-refinery throughput limit,
surplus-crude direct sale, and the no-double-billing contract on
refinery process load (it counts toward dispatch demand but earns no
retail revenue).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from world.api import create_app
from world.catalog import build_catalog
from world.economy import (
    REFINED_PRICE_USD_PER_BBL,
    REFINERY_KWH_PER_BBL,
    REFINERY_MAX_BBL_DAY,
    REFINERY_YIELD,
    refine_one,
    refinery_process_kw,
    route_crude,
)
from world.sim import World
from world.state import Tile
from world.subsurface import CRUDE_PRICE_USD_PER_BBL, Q_MAX_WELL_BBL_DAY, Voxel


def _hc_voxel(world: World) -> Voxel:
    return next(iter(world.subsurface.voxels.values()))


def _refinery_tile(rid: str, setpoint: float) -> Tile:
    return Tile(
        id=rid,
        type="refinery",
        x=0,
        y=0,
        built_day=0,
        operational=True,
        setpoint_rate_bbl_day=setpoint,
    )


def _build_road_link(world: World, x: int, y: int) -> None:
    """Drop a road tile bridging town hall to (x, y) so a refinery built
    nearby has road adjacency."""
    th = next(t for t in world.state.tiles if t.type == "town_hall")
    # Walk from town_hall to (x, y) along x then along y, dropping roads
    # everywhere except the destination cell.
    cx, cy = th.x, th.y
    while cx != x:
        cx += 1 if cx < x else -1
        if (cx, cy) == (x, y):
            return
        world.build("road", cx, cy)
    while cy != y:
        cy += 1 if cy < y else -1
        if (cx, cy) == (x, y):
            return
        world.build("road", cx, cy)


# -- refine_one (yield + caps) ---------------------------------------------


def test_refine_one_yield_is_85_percent():
    actual, refined = refine_one(setpoint_rate_bbl_day=400, available_crude_bbl=400)
    assert actual == 400
    assert refined == pytest.approx(400 * REFINERY_YIELD)


def test_refine_one_capped_at_max_throughput():
    """Setpoint above 500 is silently bounded by REFINERY_MAX_BBL_DAY."""
    actual, refined = refine_one(setpoint_rate_bbl_day=999, available_crude_bbl=1_000)
    assert actual == REFINERY_MAX_BBL_DAY
    assert refined == pytest.approx(REFINERY_MAX_BBL_DAY * REFINERY_YIELD)


def test_refine_one_capped_at_available_crude():
    """If crude runs short, actual = available_crude (refined yield applies)."""
    actual, refined = refine_one(setpoint_rate_bbl_day=400, available_crude_bbl=120)
    assert actual == 120
    assert refined == pytest.approx(120 * REFINERY_YIELD)


def test_refine_one_zero_setpoint_zero_actual():
    actual, refined = refine_one(setpoint_rate_bbl_day=0, available_crude_bbl=500)
    assert actual == 0.0
    assert refined == 0.0


# -- route_crude (priority + tiebreak) -------------------------------------


def test_route_crude_higher_setpoint_first():
    big = _refinery_tile("ref-1", setpoint=400)
    small = _refinery_tile("ref-2", setpoint=100)
    # Total crude = 450 → big takes 400, small takes 50.
    actual = route_crude([small, big], total_crude_bbl=450)
    assert actual["ref-1"] == 400
    assert actual["ref-2"] == 50


def test_route_crude_id_ascending_tiebreak():
    """Two refineries with the same setpoint: lower-id wins crude first."""
    a = _refinery_tile("refinery-1", setpoint=200)
    b = _refinery_tile("refinery-2", setpoint=200)
    # Total crude = 250 → -1 takes 200, -2 takes 50.
    actual = route_crude([b, a], total_crude_bbl=250)
    assert actual["refinery-1"] == 200
    assert actual["refinery-2"] == 50


def test_route_crude_surplus_unallocated_when_setpoints_satisfied():
    """When total_crude exceeds Σ effective setpoints, the leftover stays
    unallocated — the caller treats that as crude_direct."""
    a = _refinery_tile("ref-1", setpoint=100)
    b = _refinery_tile("ref-2", setpoint=100)
    actual = route_crude([a, b], total_crude_bbl=500)
    assert sum(actual.values()) == 200
    # Surplus = 300 → caller will sell as crude_direct at $40/bbl.


def test_route_crude_no_refineries_returns_empty():
    actual = route_crude([], total_crude_bbl=500)
    assert actual == {}


def test_route_crude_caps_per_refinery_at_max():
    """Even with infinite crude, a single refinery never refines more than
    REFINERY_MAX_BBL_DAY."""
    big = _refinery_tile("ref-1", setpoint=999)
    actual = route_crude([big], total_crude_bbl=10_000)
    assert actual["ref-1"] == REFINERY_MAX_BBL_DAY


# -- refinery_process_kw (hourly load) -------------------------------------


def test_refinery_process_kw_hourly_load():
    """Hourly load = throughput × 200 / 24."""
    assert refinery_process_kw(120) == pytest.approx(120 * REFINERY_KWH_PER_BBL / 24.0)


def test_refinery_process_kw_zero_throughput_zero_load():
    assert refinery_process_kw(0.0) == 0.0


# -- catalog ---------------------------------------------------------------


def test_catalog_exposes_refinery_spec():
    cat = build_catalog()
    refinery = next(t for t in cat["tiles"] if t["tile_type"] == "refinery")
    assert refinery["capex"] == 150_000
    assert refinery["opex_per_day"] == 300
    assert refinery["requires_road"] is True
    assert refinery["jobs"] == 25
    assert refinery["buildable"] is True


# -- /build refinery -------------------------------------------------------


def test_build_refinery_deducts_capex_with_road_adjacency():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    treasury_before = w.state.treasury
    res = w.build("refinery", th.x + 1, th.y)  # adjacent to town_hall (counts as road)
    assert res["ok"] is True
    assert w.state.treasury == treasury_before - 150_000


def test_build_refinery_rejects_no_road_adjacency():
    w = World()
    w.reset(seed=42)
    res = w.build("refinery", 0, 0)
    assert res["ok"] is False
    assert res["error"] == "no_road_adjacency"


def test_build_refinery_rejects_insufficient_funds():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.state.treasury = 100.0
    res = w.build("refinery", th.x + 1, th.y)
    assert res["ok"] is False
    assert res["error"] == "insufficient_funds"


# -- /control/refinery -----------------------------------------------------


def test_control_refinery_clamps_setpoint_above_max():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    res = w.control_refinery(rid, 999.0)
    assert res["ok"] is True
    assert res["result"]["setpoint_rate_bbl_day"] == REFINERY_MAX_BBL_DAY


def test_control_refinery_clamps_setpoint_below_zero():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    res = w.control_refinery(rid, -50.0)
    assert res["ok"] is True
    assert res["result"]["setpoint_rate_bbl_day"] == 0.0


def test_control_refinery_unknown_id():
    w = World()
    w.reset(seed=42)
    res = w.control_refinery("refinery-99", 200.0)
    assert res["ok"] is False
    assert res["error"] == "unknown_refinery"


def test_control_refinery_rejects_well_id():
    """Wells aren't refineries — control/refinery must not accept a well id."""
    w = World()
    w.reset(seed=42)
    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    well_id = w.state.wells[0].id
    res = w.control_refinery(well_id, 200.0)
    assert res["ok"] is False
    assert res["error"] == "unknown_refinery"


# -- End-to-end: routing + revenue split + process load --------------------


def test_refined_revenue_at_full_throughput():
    """Daily routing: all crude refined; refined revenue = actual × 0.85 × $90."""
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    w.control_refinery(rid, REFINERY_MAX_BBL_DAY)

    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    well_id = w.state.wells[0].id
    w.control_well(well_id, Q_MAX_WELL_BBL_DAY)

    w.step(days=1)
    rate = w.state.wells[0].current_rate_bbl_day
    refinery = next(t for t in w.state.tiles if t.type == "refinery")
    # First well's daily output is ≤ 200 bbl/day; well below the 500-bbl
    # refinery cap, so all crude is refined.
    assert refinery.current_throughput_bbl_day == pytest.approx(rate)
    # No surplus → crude_revenue = 0.
    assert w.state.today_summary_so_far["crude_revenue"] == 0.0
    expected_refined_revenue = rate * REFINERY_YIELD * REFINED_PRICE_USD_PER_BBL
    assert w.state.today_summary_so_far["refined_revenue"] == pytest.approx(
        expected_refined_revenue
    )
    assert w.state.today_summary_so_far["oil_revenue"] == pytest.approx(expected_refined_revenue)


def test_surplus_crude_sells_at_crude_price_when_no_refinery():
    """Without a refinery, today_summary_so_far.oil_revenue = total_crude × $40 —
    the existing slice-07 contract is preserved when no refinery exists."""
    w = World()
    w.reset(seed=42)
    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    well_id = w.state.wells[0].id
    w.control_well(well_id, Q_MAX_WELL_BBL_DAY)
    w.step(days=1)
    rate = w.state.wells[0].current_rate_bbl_day
    assert rate > 0
    assert w.state.today_summary_so_far["oil_revenue"] == pytest.approx(
        rate * CRUDE_PRICE_USD_PER_BBL
    )
    # Pure-crude path: refined_revenue stays at 0, crude_revenue = oil_revenue.
    assert w.state.today_summary_so_far["refined_revenue"] == 0.0
    assert w.state.today_summary_so_far["crude_revenue"] == pytest.approx(
        w.state.today_summary_so_far["oil_revenue"]
    )


def test_surplus_crude_after_refinery_setpoint_satisfied():
    """If wells produce more crude than refineries can absorb, surplus
    sells raw at $40/bbl. Construct a setup with refinery setpoint=10 so
    surplus exists."""
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    w.control_refinery(rid, 10.0)

    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    w.control_well(w.state.wells[0].id, Q_MAX_WELL_BBL_DAY)

    w.step(days=1)
    rate = w.state.wells[0].current_rate_bbl_day
    assert rate > 10  # well produces more than refinery setpoint

    refinery = next(t for t in w.state.tiles if t.type == "refinery")
    assert refinery.current_throughput_bbl_day == pytest.approx(10.0)
    expected_refined_revenue = 10.0 * REFINERY_YIELD * REFINED_PRICE_USD_PER_BBL
    expected_crude_revenue = (rate - 10.0) * CRUDE_PRICE_USD_PER_BBL
    assert w.state.today_summary_so_far["refined_revenue"] == pytest.approx(
        expected_refined_revenue
    )
    assert w.state.today_summary_so_far["crude_revenue"] == pytest.approx(expected_crude_revenue)
    assert w.state.today_summary_so_far["oil_revenue"] == pytest.approx(
        expected_refined_revenue + expected_crude_revenue
    )


def test_process_load_unbilled_no_retail_revenue_from_refinery():
    """The refinery's hourly process load contributes to demand but is
    unbilled. With population=0 and no civilian tiles, civilian_demand_kw
    is 0; a refinery drawing 2000 kW of process load must produce zero
    retail revenue (and zero export revenue, since demand exceeds supply
    so there is no curtailment surplus)."""
    w = World()
    w.reset(seed=42)
    w.state.population = 0  # zero out civilian load
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    refinery = next(t for t in w.state.tiles if t.type == "refinery")
    # Pin throughput so it draws process load immediately on day 1's hourly
    # loop (skipping the production-loop lag).
    refinery.current_throughput_bbl_day = 240.0  # 240 × 200 / 24 = 2000 kW/h
    w.build("coal_plant", th.x + 2, th.y)

    w.step(days=1)

    # Demand each hour ≥ 2000 kW (refinery load). Civilian = 0.
    for d in w.state.last_day_demand_kw_by_hour:
        assert d >= 2000.0 - 0.01
    # Refinery process load earns no retail revenue and no export revenue —
    # demand strictly exceeds supply, so there's never a surplus to export.
    assert w.state.today_summary_so_far["power_revenue"] == 0.0


def test_process_load_zero_on_day_one_then_lags_actual_throughput():
    """Day 1 has no prior actual_throughput, so refinery process load is 0.
    After day 1's production loop pins throughput, day 2's hourly loop draws
    process power."""
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    w.control_refinery(rid, REFINERY_MAX_BBL_DAY)

    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    w.control_well(w.state.wells[0].id, Q_MAX_WELL_BBL_DAY)

    w.step(days=1)  # day 1: no prior throughput → no refinery load
    refinery = next(t for t in w.state.tiles if t.type == "refinery")
    day1_throughput = refinery.current_throughput_bbl_day
    assert day1_throughput > 0  # day 1's production refined at end of day

    # Day 1 hourly demand SHOULD NOT include refinery process load (lag).
    # We can't isolate that from civilian demand here, but day 2's demand
    # WILL include it. Use last_day_demand_kw_by_hour after day 2.
    w.step(days=1)  # day 2: refinery now drawing process load all day
    expected_process_kw = day1_throughput * REFINERY_KWH_PER_BBL / 24.0
    # Every hour of day 2 includes at least the refinery process load.
    for d in w.state.last_day_demand_kw_by_hour:
        assert d >= expected_process_kw - 0.01


# -- Routing priority integration -----------------------------------------


def test_two_refineries_higher_throughput_takes_more_crude():
    """Build two refineries, set one to 400 setpoint and one to 100. With
    well producing ~150 bbl, the high-setpoint refinery takes all of it;
    the low-setpoint refinery refines 0."""
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    w.build("refinery", th.x - 1, th.y)
    refs = [t for t in w.state.tiles if t.type == "refinery"]
    high = next(r for r in refs if r.x == th.x + 1)
    low = next(r for r in refs if r.x == th.x - 1)
    w.control_refinery(high.id, 400.0)
    w.control_refinery(low.id, 100.0)

    hc = _hc_voxel(w)
    w.drill(hc.x, hc.y, hc.z, "production")
    w.control_well(w.state.wells[0].id, Q_MAX_WELL_BBL_DAY)

    w.step(days=1)
    rate = w.state.wells[0].current_rate_bbl_day
    # High-throughput refinery gets all crude (rate ≤ 400 ≤ its setpoint).
    high_after = next(r for r in w.state.tiles if r.id == high.id)
    low_after = next(r for r in w.state.tiles if r.id == low.id)
    if rate <= 400:
        assert high_after.current_throughput_bbl_day == pytest.approx(rate)
        assert low_after.current_throughput_bbl_day == 0.0
    else:
        assert high_after.current_throughput_bbl_day == pytest.approx(400)
        assert low_after.current_throughput_bbl_day == pytest.approx(min(100.0, rate - 400))


# -- API smoke ------------------------------------------------------------


def test_api_build_refinery():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    client = TestClient(create_app(world=w))
    res = client.post("/build", json={"tile_type": "refinery", "x": th.x + 1, "y": th.y}).json()
    assert res["ok"] is True


def test_api_control_refinery_endpoint():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    client = TestClient(create_app(world=w))
    client.post("/build", json={"tile_type": "refinery", "x": th.x + 1, "y": th.y})
    refinery = next(t for t in w.state.tiles if t.type == "refinery")
    res = client.post(
        "/control/refinery", json={"refinery_id": refinery.id, "rate_bbl_day": 250.0}
    ).json()
    assert res["ok"] is True
    assert res["result"]["setpoint_rate_bbl_day"] == 250.0


def test_api_control_refinery_unknown_id():
    w = World()
    w.reset(seed=42)
    client = TestClient(create_app(world=w))
    res = client.post(
        "/control/refinery", json={"refinery_id": "refinery-99", "rate_bbl_day": 200.0}
    ).json()
    assert res["ok"] is False
    assert res["error"] == "unknown_refinery"


# -- /state.tiles schema ---------------------------------------------------


def test_state_tiles_refinery_exposes_setpoint_and_throughput():
    w = World()
    w.reset(seed=42)
    th = next(t for t in w.state.tiles if t.type == "town_hall")
    w.build("refinery", th.x + 1, th.y)
    rid = next(t.id for t in w.state.tiles if t.type == "refinery")
    w.control_refinery(rid, 320.0)
    s = w.state_dict()
    refinery = next(t for t in s["tiles"] if t["type"] == "refinery")
    assert refinery["setpoint_rate_bbl_day"] == 320.0
    assert refinery["current_throughput_bbl_day"] == 0.0  # not yet stepped


# -- Determinism -----------------------------------------------------------


def test_step_size_invariance_with_refinery():
    """Refinery routing is RNG-free, so step(7) ≡ step(1)×7."""
    a = World()
    b = World()
    a.reset(seed=42)
    b.reset(seed=42)
    for w in (a, b):
        th = next(t for t in w.state.tiles if t.type == "town_hall")
        w.build("refinery", th.x + 1, th.y)
        rid = next(t.id for t in w.state.tiles if t.type == "refinery")
        w.control_refinery(rid, REFINERY_MAX_BBL_DAY)
        hc = _hc_voxel(w)
        w.drill(hc.x, hc.y, hc.z, "production")
        w.control_well(w.state.wells[0].id, Q_MAX_WELL_BBL_DAY)
    a.step(days=7)
    for _ in range(7):
        b.step(days=1)
    assert a.state.treasury == pytest.approx(b.state.treasury)
    a_ref = next(t for t in a.state.tiles if t.type == "refinery")
    b_ref = next(t for t in b.state.tiles if t.type == "refinery")
    assert a_ref.current_throughput_bbl_day == pytest.approx(b_ref.current_throughput_bbl_day)
