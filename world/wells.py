"""End-of-day well operations.

Two phases that ``_advance_one_day`` runs after the 24-tick hourly loop
completes, on the per-well bookkeeping ``commit_tick`` accumulated into
``state.today.inj_bbl_by_well`` and ``state.today.prod_kwh_by_well``:

  * ``commit_well_injections`` — pin each injector's daily bbl total and
    bump its lifetime cumulative.
  * ``run_production_loop`` — for each producer, resolve qualifying
    injectors (same reservoir, Chebyshev distance > 1), compute the
    rate-based ``pressure_boost``, then ``well_production_bbl_day``, then
    cap by the day's allocated power budget.

The order is load-bearing: producers don't read injection cumulative,
but they DO read every injector's ``yesterday_rate_bbl_day`` to compute
the qualifying-injector rate term. That snapshot was taken at the top of
``_advance_one_day``, so the only sequencing constraint here is that
``commit_well_injections`` lands before ``route_oil`` (which reads
``well.current_rate_bbl_day`` to size each network's crude pool).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world import workforce
from world.subsurface import PRESSURE_BOOST_MAX, PRODUCTION_KWH_PER_BBL, injector_supports
from world.subsurface import well_production_bbl_day as _well_production_bbl_day

if TYPE_CHECKING:
    from world.sim import World
    from world.state import Well, WorldState


def commit_well_injections(state: WorldState) -> None:
    """Pin each injection well's daily bbl total + lifetime cumulative.

    ``commit_tick`` accumulated per-well bbl into
    ``state.today.inj_bbl_by_well`` across the 24 ticks; this writes the
    sum back to each well's ``current_rate_bbl_day`` and bumps
    ``cumulative_injected_bbl``. An injector that was never assigned
    power this day (e.g., the grid was blacked out every hour) has no
    entry in the dict and stays at 0.0.
    """
    for w in state.wells:
        if w.type != "injection":
            continue
        bbl = state.today.inj_bbl_by_well.get(w.id, 0.0)
        w.current_rate_bbl_day = bbl
        w.cumulative_injected_bbl += bbl


def run_production_loop(world: World) -> None:
    """Producer daily output (brief §4.5, oilfield-v2 §"Rate-based pressure").

    For each producer in creation order (``state.wells`` is appended-to
    on ``/drill`` — deterministic for shared-pool resolution):

      1. Sum qualifying injectors' ``yesterday_rate_bbl_day``. Qualifying
         injectors share the producer's ``reservoir_id`` AND sit at
         Chebyshev distance > 1 from the producer's target (the
         ``injector_supports`` helper owns that gate, shared with
         ``well_view`` so /state and the daily calc match).
      2. Stamp telemetry on the producer (``yesterday_inj_rate_bbl_day``,
         ``pressure_boost``) for the /state popup.
      3. Call ``well_production_bbl_day`` against the subsurface grid
         with that injector rate + producer's own yesterday rate.
      4. Cap throughput by ``state.today.prod_kwh_by_well[id] /
         PRODUCTION_KWH_PER_BBL``. At balanced/curtailment the budget
         equals setpoint × eff (geology binds); when the grid shed the
         well during brownout/blackout hours, the budget shrinks and
         pins throughput at the equivalent of the kWh actually
         delivered.
      5. Pin ``current_rate_bbl_day`` and bump ``cumulative_produced_bbl``.
    """
    state = world.state

    qualifying_injectors_by_prod: dict[str, list[Well]] = {}
    for iw in state.wells:
        if iw.type != "injection":
            continue
        for prod_id in injector_supports(iw, state.wells):
            qualifying_injectors_by_prod.setdefault(prod_id, []).append(iw)

    for well in state.wells:
        if well.type != "production":
            continue
        qualifying_inj_rate = sum(
            iw.yesterday_rate_bbl_day for iw in qualifying_injectors_by_prod.get(well.id, [])
        )
        well.yesterday_inj_rate_bbl_day = qualifying_inj_rate
        well.pressure_boost = min(
            PRESSURE_BOOST_MAX,
            qualifying_inj_rate / max(well.yesterday_rate_bbl_day, 1.0),
        )
        q = _well_production_bbl_day(
            world.subsurface,
            well.x,
            well.y,
            well.target_z,
            well.setpoint_rate_bbl_day,
            qualifying_inj_rate_bbl_day=qualifying_inj_rate,
            producer_yesterday_rate_bbl_day=well.yesterday_rate_bbl_day,
            efficiency=workforce.efficiency(well),
        )
        power_allocated_bbl = (
            state.today.prod_kwh_by_well.get(well.id, 0.0) / PRODUCTION_KWH_PER_BBL
        )
        q = min(q, power_allocated_bbl)
        well.current_rate_bbl_day = q
        well.cumulative_produced_bbl += q
