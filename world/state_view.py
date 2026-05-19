"""External-facing dict shapes for ``World`` mutators and ``/state``.

`World.build()` / `World.drill()` / `World.state_dict()` (and indirectly the
UI, agents, tests) consume these projectors to turn a single ``Tile`` or
``Well`` into the dict the API surfaces. Pure functions, no mutation, no
I/O — given the same ``(tile|well, world)`` they always return the same
dict. Co-located here so the wire format is one grep target, not 120 lines
buried at the top of the simulation loop.

Popup economics live here as private ``_EconomicsRow`` helpers
(``_plant_row``, ``_refinery_row``, …) rather than as public
``*_for_tile`` helpers in ``world.economy``. The popup row is consumed
only by ``tile_view``; the economy module owns the dual-consumer helpers
(industrial / commercial revenue + CO2) that the end-of-day aggregator
also reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from world.catalog import TILE_CATALOG
from world.economy import (
    COMMERCIAL_RADIUS,
    REFINERY_CO2_PER_BBL,
    REFINERY_YIELD,
    commercial_revenue_for_tile,
    industrial_co2_for_tile,
    industrial_revenue_for_tile,
    occupancy_ratio,
)
from world.power import PLANT_TYPES
from world.subsurface import INJECTION_KWH_PER_BBL, injector_supports

if TYPE_CHECKING:
    from world.sim import World
    from world.state import Tile, Well, WorldState


class _EconomicsRow(NamedTuple):
    """Popup-row five-tuple for one ``Tile``.

    Spread into the wire-format dict by ``tile_view`` as
    ``estimated_{revenue,co2,fuel_cost,carbon_cost,net}_per_day``. Defaults
    are 0.0 across the board so per-type helpers (``_plant_row``,
    ``_refinery_row``, …) only set the fields they care about.
    """

    revenue: float = 0.0
    co2_t: float = 0.0
    fuel_cost: float = 0.0
    carbon_cost: float = 0.0
    net: float = 0.0


_ZERO_ROW = _EconomicsRow()


def _industrial_row(state: WorldState, tile: Tile) -> _EconomicsRow:
    revenue = industrial_revenue_for_tile(state, tile)
    co2_t = industrial_co2_for_tile(tile)
    carbon_cost = co2_t * state.carbon_price
    return _EconomicsRow(
        revenue=revenue,
        co2_t=co2_t,
        carbon_cost=carbon_cost,
        net=revenue - tile.opex_per_day - carbon_cost,
    )


def _commercial_row(state: WorldState, tile: Tile) -> _EconomicsRow:
    revenue = commercial_revenue_for_tile(state, tile)
    return _EconomicsRow(
        revenue=revenue,
        net=revenue - tile.opex_per_day,
    )


def _plant_row(state: WorldState, tile: Tile) -> _EconomicsRow:
    """Plant popup row, priced on yesterday's served kWh.

    Non-operational plants return zero revenue/co2/fuel/carbon and
    ``net = -opex`` so the popup shows the standing OPEX cost of a
    plant that produced nothing today.
    """
    spec = TILE_CATALOG[tile.type]
    if not tile.operational:
        return _EconomicsRow(net=-tile.opex_per_day)
    mwh = tile.kwh_served_yesterday / 1000.0
    cost_per_mwh = state.plant_fuel_cost_per_mwh.get(tile.type, spec.fuel_cost_per_mwh)
    revenue = tile.kwh_served_yesterday * state.grid_price_retail
    fuel_cost = mwh * cost_per_mwh
    co2_t = mwh * spec.co2_t_per_mwh
    carbon_cost = co2_t * state.carbon_price
    return _EconomicsRow(
        revenue=revenue,
        co2_t=co2_t,
        fuel_cost=fuel_cost,
        carbon_cost=carbon_cost,
        net=revenue - tile.opex_per_day - fuel_cost - carbon_cost,
    )


def _refinery_row(state: WorldState, tile: Tile) -> _EconomicsRow:
    """Refinery popup row, priced on yesterday's pinned throughput."""
    if not tile.operational:
        return _EconomicsRow(net=-tile.opex_per_day)
    revenue = tile.current_throughput_bbl_day * REFINERY_YIELD * state.refined_price_usd_per_bbl
    co2_t = tile.current_throughput_bbl_day * REFINERY_CO2_PER_BBL
    carbon_cost = co2_t * state.carbon_price
    return _EconomicsRow(
        revenue=revenue,
        co2_t=co2_t,
        carbon_cost=carbon_cost,
        net=revenue - tile.opex_per_day - carbon_cost,
    )


def tile_view(t: Tile, world: World) -> dict[str, Any]:
    """Wire-format dict for one ``Tile`` at its current operating state.

    Dispatches by tile type to one of the ``_*_row`` helpers for the
    popup economics; tiles with no economics row (``town_hall``,
    ``road``, ``house``, ``pipeline``, ``battery``) report a zero row.
    ``residents_in_radius`` on commercial tiles is the
    capacity-in-radius × city occupancy figure the popup needs and is
    computed locally — it exists only to feed this dict.
    """
    state = world.state
    extra: dict[str, Any] = {}
    if t.type == "industrial":
        row = _industrial_row(state, t)
    elif t.type == "commercial":
        row = _commercial_row(state, t)
        extra["residents_in_radius"] = _residents_in_radius(state, t)
    elif t.type in PLANT_TYPES:
        row = _plant_row(state, t)
    elif t.type == "refinery":
        row = _refinery_row(state, t)
    else:
        row = _ZERO_ROW
    return {
        "id": t.id,
        "type": t.type,
        "x": t.x,
        "y": t.y,
        "built_day": t.built_day,
        "operational": t.operational,
        "capex_paid": t.capex_paid,
        "opex_per_day": t.opex_per_day,
        "housing_capacity": t.housing_capacity,
        "jobs": t.jobs,
        "demand_kw": t.demand_kw,
        "staffed_jobs": t.staffed_jobs,
        "current_output_kw": t.current_output_kw,
        "kwh_served_today": t.kwh_served_today,
        "kwh_served_yesterday": t.kwh_served_yesterday,
        "setpoint_rate_bbl_day": t.setpoint_rate_bbl_day,
        "current_throughput_bbl_day": t.current_throughput_bbl_day,
        "estimated_revenue_per_day": row.revenue,
        "estimated_co2_per_day": row.co2_t,
        "estimated_fuel_cost_per_day": row.fuel_cost,
        "estimated_carbon_cost_per_day": row.carbon_cost,
        "estimated_net_per_day": row.net,
        **extra,
        **(
            {"soc_kwh": t.soc_kwh, "charge_setpoint_kw": t.charge_setpoint_kw}
            if t.type == "battery"
            else {}
        ),
    }


def well_view(w: Well, world: World) -> dict[str, Any]:
    """Wire-format dict for one ``Well`` at its current operating state.

    Two branches (production / injection); the math is small enough
    that inlining beats extracting a row type. ``supports_producer_ids``
    mirrors the same-reservoir + Chebyshev > 1 gate that the day loop's
    ``pressure_boost`` resolution uses, so the popup row and the
    simulator share one source of truth. Producer wells carry an empty
    list for type symmetry; the UI ignores the field on producer rows.
    """
    state = world.state
    if w.type == "production":
        revenue = w.current_rate_bbl_day * state.crude_price_usd_per_bbl
        injection_kwh = 0.0
        net = revenue - w.opex_per_day
        supports: list[str] = []
    else:
        revenue = 0.0
        injection_kwh = w.current_rate_bbl_day * INJECTION_KWH_PER_BBL
        # Injection wells: power cost is internalized through plants, so Net is
        # -opex with no $-cost from kWh consumption.
        net = -w.opex_per_day
        supports = injector_supports(w, state.wells)
    return {
        "id": w.id,
        "type": w.type,
        "x": w.x,
        "y": w.y,
        "target_z": w.target_z,
        "reservoir_id": w.reservoir_id,
        "drilled_day": w.drilled_day,
        "setpoint_rate_bbl_day": w.setpoint_rate_bbl_day,
        "current_rate_bbl_day": w.current_rate_bbl_day,
        "yesterday_rate_bbl_day": w.yesterday_rate_bbl_day,
        "yesterday_inj_rate_bbl_day": w.yesterday_inj_rate_bbl_day,
        "pressure_boost": w.pressure_boost,
        "cumulative_produced_bbl": w.cumulative_produced_bbl,
        "cumulative_injected_bbl": w.cumulative_injected_bbl,
        "capex_paid": w.capex_paid,
        "opex_per_day": w.opex_per_day,
        "staffed_jobs": w.staffed_jobs,
        "supports_producer_ids": supports,
        "estimated_revenue_per_day": revenue,
        "injection_power_kwh_per_day": injection_kwh,
        "estimated_net_per_day": net,
    }


def _residents_in_radius(state: Any, tile: Tile) -> float:
    """Capacity-in-radius × city occupancy for the commercial popup row.

    Lives here (not in ``economy``) because it serves only this dict —
    it's a UI-facing convenience derived from the same data
    ``commercial_revenue_for_tile`` uses, but without the rate and
    workforce-efficiency multipliers. Inlining keeps ``economy``'s public
    surface focused on per-tile economics rather than popup helpers.
    """
    capacity_in_radius = 0
    for other in state.tiles:
        if other.housing_capacity <= 0:
            continue
        if max(abs(other.x - tile.x), abs(other.y - tile.y)) <= COMMERCIAL_RADIUS:
            capacity_in_radius += other.housing_capacity
    return capacity_in_radius * occupancy_ratio(state)
