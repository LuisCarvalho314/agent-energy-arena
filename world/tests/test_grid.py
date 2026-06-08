"""Tile placement, adjacency flood-fill, and treasury accounting."""

from __future__ import annotations

import pytest

from world.grid import (
    grid_factor,
    has_power_connection,
    is_active_substation,
    is_grid_connected,
    road_connected_set,
    transmission_connected_set,
    transmission_line_touches_power_source,
)
from world.sim import World
from world.state import Tile


def _fresh_world() -> World:
    w = World()
    w.reset(seed=42)
    return w


# -- Adjacency flood-fill ----------------------------------------------------


def test_town_hall_counts_as_road():
    """A house orthogonally adjacent to the town hall (without any roads) is valid."""
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2
    res = w.build("house", cx + 1, cy)
    assert res["ok"] is True, res
    assert any(t.type == "house" and t.x == cx + 1 and t.y == cy for t in w.state.tiles)


def test_road_chain_extends_network():
    """A house adjacent to a road that is itself connected (via roads) to the town hall is valid."""
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2
    # Lay roads stepping east of town hall.
    for dx in range(1, 4):
        r = w.build("road", cx + dx, cy)
        assert r["ok"] is True, r
    # House adjacent to the far end of the road chain.
    res = w.build("house", cx + 3, cy + 1)
    assert res["ok"] is True


def test_house_without_road_adjacency_rejected():
    w = _fresh_world()
    res = w.build("house", 0, 0)  # corner; town hall is at center.
    assert res["ok"] is False
    assert res["error"] == "no_road_adjacency"
    # World unchanged.
    assert all(t.type != "house" for t in w.state.tiles)


def test_island_road_does_not_count_as_network():
    """A road not connected to the town hall via roads cannot anchor a house."""
    w = _fresh_world()
    # Place a single isolated road in the corner.
    res_road = w.build("road", 0, 0)
    assert res_road["ok"] is True
    # House next to that island road should be rejected: the road is not
    # connected to the town hall network.
    res_house = w.build("house", 1, 0)
    assert res_house["ok"] is False
    assert res_house["error"] == "no_road_adjacency"


def test_road_connected_set_includes_town_hall_only_at_start():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2
    s = road_connected_set(w.state.tiles, w.config.world_w, w.config.world_h)
    assert (cx, cy) in s
    assert len(s) == 1


def test_park_does_not_require_road_adjacency():
    w = _fresh_world()
    res = w.build("park", 0, 0)
    assert res["ok"] is True


def test_pipeline_does_not_require_road_adjacency():
    w = _fresh_world()
    res = w.build("pipeline", 5, 5)
    assert res["ok"] is True


def test_transmission_line_and_substation_are_buildable_placeholders():
    w = _fresh_world()
    treasury_before = w.state.treasury

    line = w.build("transmission_line", 5, 5)
    assert line["ok"] is True, line
    assert line["result"]["type"] == "transmission_line"
    assert line["result"]["connected_to_power"] is False
    assert w.state.treasury == pytest.approx(treasury_before - 1_500)

    substation = w.build("substation", 6, 5)
    assert substation["ok"] is True, substation
    assert substation["result"]["type"] == "substation"
    assert substation["result"]["jobs"] == 3
    assert substation["result"]["connected_to_power"] is False
    assert w.state.treasury == pytest.approx(treasury_before - 1_500 - 22_000)


def test_transmission_line_can_corner_connect_to_town_hall():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2

    line = w.build("transmission_line", cx + 1, cy + 1)
    assert line["ok"] is True, line
    assert line["result"]["connected_to_power"] is False

    network = transmission_connected_set(w.state.tiles)
    assert (cx, cy) in network
    assert (cx + 1, cy + 1) in network


def test_transmission_line_can_corner_connect_to_generator():
    w = _fresh_world()
    solar = w.build("solar_farm", 5, 5)
    assert solar["ok"] is True, solar

    line = w.build("transmission_line", 6, 6)
    assert line["ok"] is True, line
    assert line["result"]["connected_to_power"] is True


def test_transmission_line_detects_adjacent_coal_plant_as_power_source():
    w = _fresh_world()
    coal = Tile(id="coal-test", type="coal_plant", x=5, y=5, built_day=0)
    w.state.tiles.append(coal)

    line = w.build("transmission_line", 6, 6)
    assert line["ok"] is True, line
    line_tile = next(t for t in w.state.tiles if t.id == line["result"]["id"])
    assert transmission_line_touches_power_source(line_tile, w.state.tiles) is True
    assert line["result"]["connected_to_power"] is True


def test_transmission_connected_set_flood_fills_from_town_hall():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2

    assert w.build("transmission_line", cx + 1, cy)["ok"] is True
    assert w.build("substation", cx + 2, cy)["ok"] is True
    assert w.build("transmission_line", 0, 0)["ok"] is True

    network = transmission_connected_set(w.state.tiles)
    assert (cx, cy) in network
    assert (cx + 1, cy) in network
    assert (cx + 2, cy) in network
    assert (0, 0) not in network


def test_transmission_connected_set_does_not_connect_diagonal_line_segments():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2

    assert w.build("transmission_line", cx + 1, cy)["ok"] is True
    w.state.tiles.append(
        Tile(id="diagonal-line", type="transmission_line", x=cx + 2, y=cy + 1, built_day=0)
    )

    network = transmission_connected_set(w.state.tiles)
    assert (cx + 1, cy) in network
    assert (cx + 2, cy + 1) not in network


def test_tile_views_expose_transmission_connectivity_features():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2

    isolated_substation = w.build("substation", 0, 0)
    assert isolated_substation["ok"] is True
    assert isolated_substation["result"]["is_active_substation"] is False

    solar = w.build("solar_farm", cx + 4, cy)
    assert solar["ok"] is True
    solar_tile = next(t for t in w.state.tiles if t.id == solar["result"]["id"])
    assert is_grid_connected(solar_tile, w.state.tiles) is False
    assert grid_factor(solar_tile, w.state.tiles) == pytest.approx(0.60)

    assert w.build("transmission_line", cx + 1, cy)["ok"] is True
    assert w.build("transmission_line", cx + 2, cy)["ok"] is True
    assert w.build("transmission_line", cx + 3, cy)["ok"] is True

    state_solar = next(t for t in w.state_dict()["tiles"] if t["id"] == solar_tile.id)
    assert state_solar["is_grid_connected"] is True
    assert state_solar["grid_factor"] == pytest.approx(1.0)


def test_tile_views_expose_consumer_and_substation_power_features():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2

    house = w.build("house", cx + 1, cy)
    assert house["ok"] is True
    house_tile = next(t for t in w.state.tiles if t.id == house["result"]["id"])
    town_hall = next(t for t in w.state.tiles if t.type == "town_hall")

    assert is_active_substation(town_hall, w.state.tiles) is True
    assert has_power_connection(house_tile, w.state.tiles) is True

    state_tiles = w.state_dict()["tiles"]
    state_house = next(t for t in state_tiles if t["id"] == house_tile.id)
    state_town_hall = next(t for t in state_tiles if t["type"] == "town_hall")
    assert state_house["has_power_connection"] is True
    assert state_house["connected_to_power"] is True
    assert state_town_hall["is_active_substation"] is True
    assert state_town_hall["connected_to_power"] is True

    commercial = w.build("commercial", cx, cy + 1)
    assert commercial["ok"] is True, commercial
    assert commercial["result"]["connected_to_power"] is True

    industrial = w.build("industrial", cx - 1, cy)
    assert industrial["ok"] is True, industrial
    assert industrial["result"]["connected_to_power"] is True


# -- Treasury accounting -----------------------------------------------------


def test_build_deducts_capex():
    w = _fresh_world()
    treasury_before = w.state.treasury
    res = w.build("road", 16, 17)
    assert res["ok"] is True
    assert w.state.treasury == treasury_before - 500
    assert res["treasury_after"] == w.state.treasury


def test_insufficient_funds_rejected_world_unchanged():
    w = _fresh_world()
    w.state.treasury = 100  # less than road CAPEX.
    n_tiles = len(w.state.tiles)
    res = w.build("road", 16, 17)
    assert res["ok"] is False
    assert res["error"] == "insufficient_funds"
    assert w.state.treasury == 100
    assert len(w.state.tiles) == n_tiles


def test_tile_occupied_rejected():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2
    # Town hall is at (cx, cy).
    res = w.build("road", cx, cy)
    assert res["ok"] is False
    assert res["error"] == "tile_occupied"
    # And a freshly placed road is also occupied.
    w.build("road", cx + 1, cy)
    again = w.build("road", cx + 1, cy)
    assert again["ok"] is False
    assert again["error"] == "tile_occupied"


def test_unknown_tile_type_rejected():
    w = _fresh_world()
    res = w.build("not_a_tile", 1, 1)
    assert res["ok"] is False
    assert res["error"] == "unknown_tile_type"


def test_build_oil_well_rejected_via_build_endpoint():
    """Wells are exclusively created via /drill (PRD)."""
    w = _fresh_world()
    res = w.build("oil_well", 1, 1)
    assert res["ok"] is False
    assert res["error"] == "unknown_tile_type"


def test_out_of_bounds_rejected():
    w = _fresh_world()
    res = w.build("road", -1, 0)
    assert res["ok"] is False
    assert res["error"] == "out_of_bounds"
    res = w.build("road", w.config.world_w, 0)
    assert res["ok"] is False
    assert res["error"] == "out_of_bounds"


# -- Demolition --------------------------------------------------------------


def test_demolish_refunds_25_percent():
    w = _fresh_world()
    cx, cy = w.config.world_w // 2, w.config.world_h // 2
    # Build a house ($3000) next to the town hall.
    w.build("house", cx + 1, cy)
    treasury_after_build = w.state.treasury
    res = w.demolish(cx + 1, cy)
    assert res["ok"] is True
    assert w.state.treasury == pytest.approx(treasury_after_build + 0.25 * 3000)


def test_demolish_empty_tile_rejected():
    w = _fresh_world()
    res = w.demolish(0, 0)
    assert res["ok"] is False
    assert res["error"] == "no_tile"


def test_demolish_townhall_rejected():
    w = _fresh_world()
    cx, cy = w.config.world_w // 2, w.config.world_h // 2
    res = w.demolish(cx, cy)
    assert res["ok"] is False
    assert res["error"] == "cannot_demolish_townhall"
    # Town hall is still there.
    assert any(t.type == "town_hall" for t in w.state.tiles)


# -- Reset -------------------------------------------------------------------


def test_reset_places_town_hall_at_center():
    w = _fresh_world()
    cx = w.config.world_w // 2
    cy = w.config.world_h // 2
    halls = [t for t in w.state.tiles if t.type == "town_hall"]
    assert len(halls) == 1
    th = halls[0]
    assert th.x == cx and th.y == cy
    assert th.housing_capacity == 100
    assert th.jobs == 30


def test_reset_clears_previous_tiles():
    w = _fresh_world()
    cx, cy = w.config.world_w // 2, w.config.world_h // 2
    w.build("road", cx + 1, cy)
    w.build("house", cx + 2, cy)
    w.reset(seed=42)
    # Only the town hall remains.
    assert len(w.state.tiles) == 1
    assert w.state.tiles[0].type == "town_hall"


# -- Daily OPEX accrual ------------------------------------------------------


def test_daily_opex_deducted_during_step():
    w = _fresh_world()
    cx, cy = w.config.world_w // 2, w.config.world_h // 2
    # House: $20/day OPEX. Road: $0.
    w.build("road", cx + 1, cy)
    w.build("house", cx + 2, cy)
    # Zero out population so tax revenue (slice 03) doesn't confound the OPEX
    # delta we're asserting on. Town hall jobs(30) >= pop(0) and capacity > pop
    # so the grow branch evaluates to growth=min(0,...,30)=0; pop stays at 0.
    w.state.population = 0
    treasury_before = w.state.treasury
    w.step(days=1)
    # OPEX = 20 (house) + 0 (road) + 0 (town_hall) = 20.
    assert w.state.treasury == pytest.approx(treasury_before - 20.0)


def test_daily_opex_summary_field_populated():
    w = _fresh_world()
    cx, cy = w.config.world_w // 2, w.config.world_h // 2
    w.build("road", cx + 1, cy)
    w.build("house", cx + 2, cy)  # $20/day
    w.state.population = 0  # isolate OPEX from tax revenue.
    summary = w.step(days=3)
    # 3 days × $20 = $60.
    assert summary.summary["delta"] == pytest.approx(-60.0)


def test_step_size_invariance_with_tiles():
    """Adding tiles must not break the determinism contract from slice 01."""
    a = World()
    a.reset(seed=42)
    cx, cy = a.config.world_w // 2, a.config.world_h // 2
    a.build("road", cx + 1, cy)
    a.build("house", cx + 2, cy)
    a.step(days=7)

    b = World()
    b.reset(seed=42)
    b.build("road", cx + 1, cy)
    b.build("house", cx + 2, cy)
    for _ in range(7):
        b.step(days=1)

    assert a.state.treasury == b.state.treasury
    assert a.state.population == b.state.population
    assert a.state.day == b.state.day == 7
    # And both RNG streams match.
    assert a.sim_rng.standard_normal() == b.sim_rng.standard_normal()
