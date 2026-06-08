"""Surface-grid helpers: bounds checks and infrastructure adjacency.

The road network is the connected component (4-connected) of road and
town-hall tiles that contains the town hall. A new civilian tile that
requires road adjacency must have at least one orthogonal neighbor inside
this network — i.e. an island road in a corner cannot anchor a house.

The transmission network is rooted at the town hall. Transmission line
segments connect to each other orthogonally, while equipment interconnects
(town hall / substations / generators) use the surrounding 3x3 footprint so
corner-touching equipment still counts as connected.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from world.state import Tile

# Tile types that participate in the road network for adjacency purposes.
ROAD_TYPES: frozenset[str] = frozenset({"road", "town_hall"})
TRANSMISSION_TYPES: frozenset[str] = frozenset({"transmission_line", "substation", "town_hall"})
ACTIVE_SUBSTATION_TYPES: frozenset[str] = frozenset({"substation", "town_hall"})
PLANT_TYPES: frozenset[str] = frozenset({"solar_farm", "wind_turbine", "coal_plant", "gas_peaker"})
CONSUMER_TYPES: frozenset[str] = frozenset({"house", "commercial", "industrial"})
POWER_CONSUMER_TILE_TYPES: frozenset[str] = CONSUMER_TYPES | frozenset({"town_hall", "refinery"})
POWER_CONNECTION_FIELD_TYPES: frozenset[str] = (
    TRANSMISSION_TYPES | CONSUMER_TYPES | frozenset({"battery", "town_hall"})
)

LOCAL_DISTRIBUTION_RADIUS: int = 2
POWER_SERVICE_RADIUS: int = 3
DISCONNECTED_GRID_FACTOR: float = 0.60

_ORTHO: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
_ADJACENT_8: tuple[tuple[int, int], ...] = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


def in_bounds(x: int, y: int, w: int, h: int) -> bool:
    return 0 <= x < w and 0 <= y < h


def road_connected_set(tiles: Iterable[Tile], world_w: int, world_h: int) -> set[tuple[int, int]]:
    """4-connected flood-fill of road/town_hall tiles starting from town hall.

    Returns the set of (x, y) coordinates reachable. Empty if no town hall
    exists (which should not happen post-reset, but the function stays
    defensive).
    """
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    start: tuple[int, int] | None = None
    for pos, t in by_pos.items():
        if t.type == "town_hall":
            start = pos
            break
    if start is None:
        return set()

    seen: set[tuple[int, int]] = {start}
    stack: list[tuple[int, int]] = [start]
    while stack:
        x, y = stack.pop()
        for dx, dy in _ORTHO:
            nx, ny = x + dx, y + dy
            if not in_bounds(nx, ny, world_w, world_h):
                continue
            if (nx, ny) in seen:
                continue
            tile = by_pos.get((nx, ny))
            if tile is None or tile.type not in ROAD_TYPES:
                continue
            seen.add((nx, ny))
            stack.append((nx, ny))
    return seen


def has_road_adjacency(x: int, y: int, tiles: Iterable[Tile], world_w: int, world_h: int) -> bool:
    """True iff (x, y) has an orthogonal neighbor inside the town-hall road network."""
    network = road_connected_set(tiles, world_w, world_h)
    if not network:
        return False
    return any((x + dx, y + dy) in network for dx, dy in _ORTHO)


def transmission_connected_set(tiles: Iterable[Tile]) -> set[tuple[int, int]]:
    """Flood-fill transmission/substation tiles from town_hall.

    Returns all (x, y) positions reachable from the town_hall via
    transmission_line, substation, or town_hall tiles. Line-to-line links are
    orthogonal; line-to-substation and line-to-town_hall interconnects may use
    any of the surrounding 8 cells. Empty if no town hall exists.
    """
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    start: tuple[int, int] | None = None
    for pos, t in by_pos.items():
        if t.type == "town_hall":
            start = pos
            break
    if start is None:
        return set()

    seen: set[tuple[int, int]] = {start}
    stack: list[tuple[int, int]] = [start]
    while stack:
        x, y = stack.pop()
        tile_here = by_pos[(x, y)]
        for dx, dy in _ADJACENT_8:
            neighbor = (x + dx, y + dy)
            if neighbor in seen:
                continue
            tile = by_pos.get(neighbor)
            if tile is None or tile.type not in TRANSMISSION_TYPES:
                continue
            is_orthogonal = (dx, dy) in _ORTHO
            is_equipment_interconnect = (
                tile_here.type in ACTIVE_SUBSTATION_TYPES or tile.type in ACTIVE_SUBSTATION_TYPES
            )
            if not is_orthogonal and not is_equipment_interconnect:
                continue
            seen.add(neighbor)
            stack.append(neighbor)
    return seen


def active_substation_positions(tiles: Iterable[Tile]) -> set[tuple[int, int]]:
    """Positions of town_hall/substation tiles in the active transmission component."""
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    network = transmission_connected_set(tiles)
    return {
        pos
        for pos in network
        if (tile := by_pos.get(pos)) is not None and tile.type in ACTIVE_SUBSTATION_TYPES
    }


def is_active_substation(tile: Tile, tiles: Iterable[Tile]) -> bool:
    """True for town_hall/substation tiles in the active transmission component."""
    if tile.type not in ACTIVE_SUBSTATION_TYPES:
        return False
    return (tile.x, tile.y) in active_substation_positions(tiles)


def has_local_distribution(x: int, y: int, tiles: Iterable[Tile]) -> bool:
    """True iff an active substation/town_hall is within the 5x5 service area."""
    substations = active_substation_positions(tiles)
    return any(max(abs(x - sx), abs(y - sy)) <= LOCAL_DISTRIBUTION_RADIUS for sx, sy in substations)


def is_grid_connected(tile: Tile, tiles: Iterable[Tile]) -> bool:
    """True iff a plant touches the active transmission network in its 3x3 yard."""
    if tile.type not in PLANT_TYPES:
        return False
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    network = transmission_connected_set(tiles)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            pos = (tile.x + dx, tile.y + dy)
            neighbor = by_pos.get(pos)
            if neighbor is None:
                continue
            if neighbor.type in TRANSMISSION_TYPES and pos in network:
                return True
    return False


def grid_factor(tile: Tile, tiles: Iterable[Tile]) -> float:
    """Plant output delivery factor for the transmission v1 rule."""
    return 1.0 if power_source_connected(tile, tiles) else DISCONNECTED_GRID_FACTOR


def grid_factor_with_consumers(
    tile: Tile,
    tiles: Iterable[Tile],
    wells: Iterable[Any] = (),
) -> float:
    """Plant output delivery factor using the consumer-aware production rule."""
    return 1.0 if power_source_connected(tile, tiles, wells) else DISCONNECTED_GRID_FACTOR


def has_power_connection(tile: Tile, tiles: Iterable[Tile]) -> bool:
    """Consumer-side power connectivity.

    Houses/commercial tiles need an active substation/town_hall in their 5x5
    local distribution footprint. Industrial tiles can also connect through
    direct orthogonal adjacency to an active transmission line.
    """
    if tile.type not in CONSUMER_TYPES:
        return False
    if has_local_distribution(tile.x, tile.y, tiles):
        return True
    if tile.type != "industrial":
        return False

    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    network = transmission_connected_set(tiles)
    for dx, dy in _ORTHO:
        pos = (tile.x + dx, tile.y + dy)
        neighbor = by_pos.get(pos)
        if neighbor is not None and neighbor.type == "transmission_line" and pos in network:
            return True
    return False


def transmission_line_touches_power_source(tile: Tile, tiles: Iterable[Tile]) -> bool:
    """True iff a transmission line touches a generator in its 8-neighbourhood."""
    if tile.type != "transmission_line":
        return False
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    for dx, dy in _ADJACENT_8:
        neighbor = by_pos.get((tile.x + dx, tile.y + dy))
        if neighbor is not None and neighbor.type in PLANT_TYPES:
            return True
    return False


def powered_transmission_line_positions(tiles: Iterable[Tile]) -> set[tuple[int, int]]:
    """Transmission-line component reachable from any generator-adjacent line."""
    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
    seeds: set[tuple[int, int]] = {
        (t.x, t.y)
        for t in tiles
        if t.type == "transmission_line" and transmission_line_touches_power_source(t, tiles)
    }
    seen: set[tuple[int, int]] = set(seeds)
    stack: list[tuple[int, int]] = list(seeds)
    while stack:
        x, y = stack.pop()
        for dx, dy in _ORTHO:
            pos = (x + dx, y + dy)
            if pos in seen:
                continue
            neighbor = by_pos.get(pos)
            if neighbor is None or neighbor.type != "transmission_line":
                continue
            seen.add(pos)
            stack.append(pos)
    return seen


def _line_component_from_starts(
    starts: set[tuple[int, int]], by_pos: dict[tuple[int, int], Tile]
) -> set[tuple[int, int]]:
    seen: set[tuple[int, int]] = set(starts)
    stack: list[tuple[int, int]] = list(starts)
    while stack:
        x, y = stack.pop()
        for dx, dy in _ORTHO:
            pos = (x + dx, y + dy)
            if pos in seen:
                continue
            neighbor = by_pos.get(pos)
            if neighbor is None or neighbor.type != "transmission_line":
                continue
            seen.add(pos)
            stack.append(pos)
    return seen


def _well_near(x: int, y: int, wells: Iterable[Any], radius: int) -> bool:
    for well in wells:
        wx = getattr(well, "x", None)
        wy = getattr(well, "y", None)
        if wx is None or wy is None:
            continue
        if max(abs(x - wx), abs(y - wy)) <= radius:
            return True
    return False


def _consumer_tile_near(x: int, y: int, tiles: Iterable[Tile], radius: int) -> bool:
    return any(
        t.type in POWER_CONSUMER_TILE_TYPES
        and max(abs(x - t.x), abs(y - t.y)) <= radius
        for t in tiles
    )


def connected_to_power(tile: Tile, tiles: Iterable[Tile]) -> bool:
    """Common wire-format power-connection flag for grid-relevant tiles."""
    if tile.type == "transmission_line":
        return (tile.x, tile.y) in powered_transmission_line_positions(tiles)
    if tile.type in ACTIVE_SUBSTATION_TYPES:
        by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
        powered_lines = powered_transmission_line_positions(tiles)
        for dx, dy in _ADJACENT_8:
            pos = (tile.x + dx, tile.y + dy)
            if pos in powered_lines:
                return True
            neighbor = by_pos.get(pos)
            if neighbor is not None and neighbor.type in PLANT_TYPES:
                return True
        return False
    if tile.type in CONSUMER_TYPES:
        if tile.type == "industrial":
            powered_lines = powered_transmission_line_positions(tiles)
            if any((tile.x + dx, tile.y + dy) in powered_lines for dx, dy in _ADJACENT_8):
                return True
        for other in tiles:
            if max(abs(tile.x - other.x), abs(tile.y - other.y)) > POWER_SERVICE_RADIUS:
                continue
            if other.type in PLANT_TYPES:
                return True
            if other.type in ACTIVE_SUBSTATION_TYPES and connected_to_power(other, tiles):
                return True
        return False
    if tile.type == "battery":
        by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles}
        for dx, dy in _ADJACENT_8:
            neighbor = by_pos.get((tile.x + dx, tile.y + dy))
            if neighbor is not None and neighbor.type in PLANT_TYPES:
                return True
        for other in tiles:
            if max(abs(tile.x - other.x), abs(tile.y - other.y)) > POWER_SERVICE_RADIUS:
                continue
            if other.type in ACTIVE_SUBSTATION_TYPES and connected_to_power(other, tiles):
                return True
        return False
    return False


def generator_has_consumer(
    tile: Tile,
    tiles: Iterable[Tile],
    wells: Iterable[Any] = (),
) -> bool:
    """True iff a generator has at least one local or network-reached consumer."""
    if tile.type not in PLANT_TYPES:
        return False

    tiles_list = list(tiles)
    if _consumer_tile_near(tile.x, tile.y, tiles_list, POWER_SERVICE_RADIUS):
        return True
    if _well_near(tile.x, tile.y, wells, POWER_SERVICE_RADIUS):
        return True

    by_pos: dict[tuple[int, int], Tile] = {(t.x, t.y): t for t in tiles_list}
    starts = {
        (tile.x + dx, tile.y + dy)
        for dx, dy in _ADJACENT_8
        if (line := by_pos.get((tile.x + dx, tile.y + dy))) is not None
        and line.type == "transmission_line"
    }
    if not starts:
        return False

    component = _line_component_from_starts(starts, by_pos)
    for x, y in component:
        if _well_near(x, y, wells, 1):
            return True
        for dx, dy in _ADJACENT_8:
            pos = (x + dx, y + dy)
            neighbor = by_pos.get(pos)
            if neighbor is not None and neighbor.type == "industrial":
                return True
            if neighbor is None or neighbor.type not in ACTIVE_SUBSTATION_TYPES:
                continue
            if _consumer_tile_near(neighbor.x, neighbor.y, tiles_list, POWER_SERVICE_RADIUS):
                return True
            if _well_near(neighbor.x, neighbor.y, wells, POWER_SERVICE_RADIUS):
                return True
    return False


def power_source_connected(
    tile: Tile,
    tiles: Iterable[Tile],
    wells: Iterable[Any] = (),
) -> bool:
    """True iff a generator can export to at least one consumer."""
    return generator_has_consumer(tile, tiles, wells)
