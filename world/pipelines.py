"""Pipeline graph helpers + per-network crude routing.

A *pipeline tile* is a `Tile` with `type == "pipeline"`. Two pipeline tiles
belong to the same component iff they are orthogonally adjacent (Manhattan
distance 1); diagonals do not connect. A well or refinery belongs to a
component iff one of its four orthogonal neighbours is a pipeline tile in
that component; otherwise it is an *orphan* with respect to crude routing.

The graph helpers (``pipeline_components``, ``routing_units``,
``peaker_supply``) are pure — no `World` dependency, no mutation,
testable without a sim instance. ``route_oil`` is the end-of-day phase
that walks the routing units, settles each refinery's throughput, and
credits crude/refined revenue to ``state.today`` and ``state.treasury``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING

from world.economy import REFINERY_YIELD, route_crude
from world.state import Tile, Well

if TYPE_CHECKING:
    from world.state import WorldState

_ORTHO: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


def pipeline_components(
    tiles: Iterable[Tile], world_w: int, world_h: int
) -> list[set[tuple[int, int]]]:
    """Return 4-connected components of pipeline tiles as sets of `(x, y)`.

    Components are returned in deterministic order: the lowest-(y, x) cell
    of each component seeds it, and components are ordered by their seed.
    """
    pipes: set[tuple[int, int]] = {(t.x, t.y) for t in tiles if t.type == "pipeline"}
    seen: set[tuple[int, int]] = set()
    components: list[set[tuple[int, int]]] = []
    for start in sorted(pipes, key=lambda p: (p[1], p[0])):
        if start in seen:
            continue
        comp: set[tuple[int, int]] = {start}
        seen.add(start)
        queue: deque[tuple[int, int]] = deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in _ORTHO:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < world_w and 0 <= ny < world_h):
                    continue
                if (nx, ny) in seen:
                    continue
                if (nx, ny) not in pipes:
                    continue
                seen.add((nx, ny))
                comp.add((nx, ny))
                queue.append((nx, ny))
        components.append(comp)
    return components


def routing_units(
    tiles: Iterable[Tile], wells: Iterable[Well]
) -> tuple[
    list[tuple[list[Well], list[Tile]]],
    list[Well],
    list[Tile],
]:
    """Group wells and refineries by 4-connected pipeline component.

    Returns ``(networks, orphan_wells, orphan_refineries)`` where each
    network is ``(wells_in_network, refineries_in_network)``. A well or
    refinery is assigned to a component iff one of its orthogonal
    neighbours is a pipeline tile in that component. Anything with no
    pipeline neighbour goes to the orphan list. Components that end up
    with neither a well nor a refinery are dropped from `networks`.

    A well with pipeline neighbours in multiple components is assigned to
    the first one found (stable by component index).
    """
    tiles_list = list(tiles)
    wells_list = list(wells)

    # The bounds passed to pipeline_components only filter out-of-range
    # neighbours; since pipeline coordinates come from the input tiles
    # themselves, any bound larger than the maximum tile coordinate is
    # safe. Derive one from the inputs so callers don't have to plumb
    # world_w / world_h through.
    max_xy = 0
    for t in tiles_list:
        if t.x > max_xy:
            max_xy = t.x
        if t.y > max_xy:
            max_xy = t.y
    for wl in wells_list:
        if wl.x > max_xy:
            max_xy = wl.x
        if wl.y > max_xy:
            max_xy = wl.y
    bound = max_xy + 2

    components = pipeline_components(tiles_list, bound, bound)
    pos_to_comp: dict[tuple[int, int], int] = {}
    for idx, comp in enumerate(components):
        for pos in comp:
            pos_to_comp[pos] = idx

    refineries: list[Tile] = [t for t in tiles_list if t.type == "refinery"]

    network_wells: list[list[Well]] = [[] for _ in components]
    network_refs: list[list[Tile]] = [[] for _ in components]
    orphan_wells: list[Well] = []
    orphan_refineries: list[Tile] = []

    for wl in wells_list:
        comp_idx = _first_neighbour_component(wl.x, wl.y, pos_to_comp)
        if comp_idx is None:
            orphan_wells.append(wl)
        else:
            network_wells[comp_idx].append(wl)

    for ref in refineries:
        comp_idx = _first_neighbour_component(ref.x, ref.y, pos_to_comp)
        if comp_idx is None:
            orphan_refineries.append(ref)
        else:
            network_refs[comp_idx].append(ref)

    networks: list[tuple[list[Well], list[Tile]]] = [
        (network_wells[i], network_refs[i])
        for i in range(len(components))
        if network_wells[i] or network_refs[i]
    ]
    return networks, orphan_wells, orphan_refineries


def _first_neighbour_component(
    x: int, y: int, pos_to_comp: dict[tuple[int, int], int]
) -> int | None:
    for dx, dy in _ORTHO:
        idx = pos_to_comp.get((x + dx, y + dy))
        if idx is not None:
            return idx
    return None


def _neighbour_components(x: int, y: int, pos_to_comp: dict[tuple[int, int], int]) -> set[int]:
    found: set[int] = set()
    for dx, dy in _ORTHO:
        idx = pos_to_comp.get((x + dx, y + dy))
        if idx is not None:
            found.add(idx)
    return found


def peaker_supply(peaker_tile: Tile, tiles: Iterable[Tile]) -> bool:
    """True iff the gas peaker shares a 4-connected pipeline network with at
    least one operational refinery.

    The peaker is "on a network" iff one of its four orthogonal neighbours is
    a pipeline tile in that component (mirrors the well/refinery rule in
    `routing_units`). Diagonal adjacency does not connect. Non-operational
    refineries do not count as supply — destroying a refinery makes every
    peaker on its network unsupplied on the next call.
    """
    tiles_list = list(tiles)

    # Same bound derivation as `routing_units`: the bound only filters
    # out-of-range pipeline neighbours, so any value strictly larger than
    # the max input coord is safe.
    max_xy = 0
    for t in tiles_list:
        if t.x > max_xy:
            max_xy = t.x
        if t.y > max_xy:
            max_xy = t.y
    if peaker_tile.x > max_xy:
        max_xy = peaker_tile.x
    if peaker_tile.y > max_xy:
        max_xy = peaker_tile.y
    bound = max_xy + 2

    components = pipeline_components(tiles_list, bound, bound)
    pos_to_comp: dict[tuple[int, int], int] = {}
    for idx, comp in enumerate(components):
        for pos in comp:
            pos_to_comp[pos] = idx

    peaker_comps = _neighbour_components(peaker_tile.x, peaker_tile.y, pos_to_comp)
    if not peaker_comps:
        return False

    for t in tiles_list:
        if t.type != "refinery" or not t.operational:
            continue
        ref_comps = _neighbour_components(t.x, t.y, pos_to_comp)
        if ref_comps & peaker_comps:
            return True
    return False


def route_oil(state: WorldState) -> None:
    """End-of-day crude routing + oil revenue (brief §4.6, oilfield-v2 slice 08).

    Crude only flows from producers to refineries on the same 4-connected
    pipeline network. ``routing_units`` partitions wells + refineries by
    component. Per network, ``route_crude`` aggregates that network's
    producer crude with the same descending-setpoint / id-ascending
    tiebreak as a global call. Surplus within a network sells raw at
    ``state.crude_price_usd_per_bbl``. Orphan producers (no pipeline
    neighbour) sell 100% of their crude raw; orphan refineries (no
    pipeline neighbour or pipeline-isolated from any producer) starve
    at zero throughput.

    The yield factor is applied here (not inside ``route_crude``) so the
    routing remains purely about input allocation; one place owns the
    0.85 constant.

    Writes per-refinery ``current_throughput_bbl_day``, the day's
    ``oil_revenue`` / ``crude_revenue`` / ``refined_revenue`` on
    ``state.today``, and pins ``state.today.refined_bbl`` for
    ``settle_carbon`` to read. Credits ``state.treasury`` by oil revenue.

    Must run after ``commit_well_injections`` and ``run_production_loop``
    (which set each well's ``current_rate_bbl_day`` — the per-network
    crude pool size), and before ``settle_carbon`` (which reads
    ``state.today.refined_bbl``).
    """
    networks, orphan_wells, orphan_refineries = routing_units(state.tiles, state.wells)

    total_refined_input = 0.0
    total_routed_crude_bbl = 0.0
    for net_wells, net_refs in networks:
        net_producers = [w for w in net_wells if w.type == "production"]
        net_crude = sum(w.current_rate_bbl_day for w in net_producers)
        total_routed_crude_bbl += net_crude
        operational_refs = [r for r in net_refs if r.operational]
        per_refinery_actual = route_crude(operational_refs, net_crude)
        for r in operational_refs:
            r.current_throughput_bbl_day = per_refinery_actual.get(r.id, 0.0)
        # Non-operational refineries in this network reset to 0.
        for r in net_refs:
            if not r.operational:
                r.current_throughput_bbl_day = 0.0
        total_refined_input += sum(per_refinery_actual.values())

    # Orphan refineries: zero throughput regardless of operational flag.
    for r in orphan_refineries:
        r.current_throughput_bbl_day = 0.0

    # Orphan producers: all of their crude sells raw, independent of
    # whether a refinery happens to live elsewhere on the map.
    orphan_producer_crude_bbl = sum(
        w.current_rate_bbl_day for w in orphan_wells if w.type == "production"
    )

    networked_surplus = max(0.0, total_routed_crude_bbl - total_refined_input)
    crude_direct_bbl = networked_surplus + orphan_producer_crude_bbl
    crude_revenue = crude_direct_bbl * state.crude_price_usd_per_bbl
    refined_revenue = total_refined_input * REFINERY_YIELD * state.refined_price_usd_per_bbl
    oil_revenue = crude_revenue + refined_revenue

    # Pin today's refined input regardless of revenue (settle_carbon reads
    # it; an oil-revenue-zero day still has carbon to account for if any
    # refinery happened to process any crude — defensive, but a zero pin
    # is idempotent with the daily reset).
    state.today.refined_bbl = total_refined_input

    if oil_revenue:
        state.today.oil_revenue = oil_revenue
        state.today.crude_revenue = crude_revenue
        state.today.refined_revenue = refined_revenue
        state.treasury += oil_revenue
