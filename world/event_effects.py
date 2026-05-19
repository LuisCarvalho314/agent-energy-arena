"""Consumer-facing per-event effect queries.

Each **Event** type (CONTEXT.md) has its read-side multipliers grouped
here in a labelled section, so the locality test "what does a heatwave
do?" is satisfied by one grep. The lifecycle peer — sampling,
applying, expiring — lives in ``world.events``; the split mirrors
``hourly_tick`` (pure read) / ``commit_tick`` (mutate).

Naming convention: ``<event>_<affected_quantity>``. Example —
``heatwave_residential_mult`` (residential demand multiplier from
a heatwave); ``fuel_price_shock_bill_mult`` (per-fuel-type bill
multiplier).

Events with no read-side multiplier (``plant_failure``,
``regulatory_tightening``) are not represented here — they apply
their effect at fire time by mutating ``state`` directly (see
``world.events.sample_and_apply_events``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.state import WorldState


def _has_active(state: WorldState, event_type: str) -> bool:
    return any(e.get("type") == event_type for e in state.active_events)


# ---------------------------------------------------------------------------
# heatwave  (residential demand spike, solar panel-temperature derate)
# ---------------------------------------------------------------------------

HEATWAVE_RESIDENTIAL_MULT: float = 1.40
HEATWAVE_SOLAR_DERATE: float = 0.8


def heatwave_residential_mult(state: WorldState) -> float:
    """Residential demand multiplier from an active heatwave (A/C load).

    Returns ``HEATWAVE_RESIDENTIAL_MULT`` (1.40) iff a heatwave sits in
    ``state.active_events``, else 1.0. Industrial + commercial demand
    are unaffected (the heatwave spike is residential-only by PRD).
    """
    return HEATWAVE_RESIDENTIAL_MULT if _has_active(state, "heatwave") else 1.0


def heatwave_solar_derate(state: WorldState) -> float:
    """Per-hour solar-output multiplier from an active heatwave.

    Returns ``HEATWAVE_SOLAR_DERATE`` (0.8) iff a heatwave sits in
    ``state.active_events``, else 1.0. Wind is unaffected. Applied by
    ``hourly_tick`` against the dispatch's per-solar-plant cap so a
    solar-heavy fleet cannot ignore the event.
    """
    return HEATWAVE_SOLAR_DERATE if _has_active(state, "heatwave") else 1.0


# ---------------------------------------------------------------------------
# demand_surprise  (industrial + commercial demand spike)
# ---------------------------------------------------------------------------

DEMAND_SURPRISE_IC_MULT: float = 1.30


def demand_surprise_ic_mult(state: WorldState) -> float:
    """I+C demand multiplier from an active demand_surprise event.

    Returns ``DEMAND_SURPRISE_IC_MULT`` (1.30) iff a demand_surprise
    sits in ``state.active_events``, else 1.0. Residential demand is
    unaffected (the I+C spike is industrial/commercial-only by PRD).
    """
    return DEMAND_SURPRISE_IC_MULT if _has_active(state, "demand_surprise") else 1.0


# ---------------------------------------------------------------------------
# fuel_price_shock  (gas + coal end-of-day fuel bill)
#
# Bill-only: the shock does NOT multiply the per-MWh figure
# ``dispatch`` uses to order the coal-vs-gas merit stack. See
# docs/adr/0004-fuel-price-shock-affects-bill-not-dispatch.md.
# ---------------------------------------------------------------------------

GAS_FUEL_SHOCK_MULT: float = 2.5
COAL_FUEL_SHOCK_MULT: float = 1.3
FUEL_SHOCK_MULT_BY_TYPE: dict[str, float] = {
    "gas_peaker": GAS_FUEL_SHOCK_MULT,
    "coal_plant": COAL_FUEL_SHOCK_MULT,
}


def fuel_price_shock_bill_mult(state: WorldState, fuel_type: str) -> float:
    """End-of-day fuel-bill multiplier (≥1.0) for the named fossil
    plant type (``gas_peaker`` or ``coal_plant``). Returns 1.0 when no
    shock is active.

    Consumed by ``economy.settle_fuel`` only. Dispatch merit-order is
    intentionally unaffected — see
    docs/adr/0004-fuel-price-shock-affects-bill-not-dispatch.md.
    """
    if not _has_active(state, "fuel_price_shock"):
        return 1.0
    return FUEL_SHOCK_MULT_BY_TYPE[fuel_type]
