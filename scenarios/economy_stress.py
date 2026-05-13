"""Economy-stress scenario — fuel shock + crude collapse + regulatory step.

Three pressure sources on the economic surface, layered:

* Fuel-price shock: `state.plant_fuel_cost_per_mwh` is mutated for
  coal and gas across `FUEL_SHOCK_START_DAY..FUEL_SHOCK_END_DAY`.
  `dispatch()` reads from state, so merit order can flip live (gas
  becomes prohibitively expensive vs coal vs renewables).
* Crude-price collapse: `state.crude_price_usd_per_bbl` drops for
  `CRUDE_COLLAPSE_START_DAY..CRUDE_COLLAPSE_END_DAY`, so production
  wells run at a loss until the window closes.
* Regulatory tightening: on `REGULATORY_DAY` a permanent step bump
  is applied to `state.carbon_price` and a `regulatory_tightening`
  marker is appended to `active_events` with a chosen duration. The
  carbon-price effect is permanent (matches the stochastic
  sampler's semantics); the active-events entry exists for run-log
  visibility and expires via `expire_finite_events` at the
  configured end day.

All tuning values are class attributes. The scenario consumes no
random numbers — given `(world, day)` the effects are deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.scenario import Scenario

if TYPE_CHECKING:
    from world.sim import World


class EconomyStress(Scenario):
    """Stress the economy with fuel + crude + regulatory shocks."""

    seed: int = 42

    # Fuel-price shock window. Baseline costs are 12 (coal) and 30
    # (gas); the shock more than doubles both so the merit order can
    # flip toward renewables/idle until the window closes.
    FUEL_SHOCK_START_DAY: int = 7
    FUEL_SHOCK_END_DAY: int = 90  # exclusive
    FUEL_SHOCK_COAL_USD_PER_MWH: float = 30.0
    FUEL_SHOCK_GAS_USD_PER_MWH: float = 75.0

    # Crude collapse window. Baseline crude price is 40 $/bbl; collapse
    # to 15 forces a production-cost vs revenue decision.
    CRUDE_COLLAPSE_START_DAY: int = 14
    CRUDE_COLLAPSE_END_DAY: int = 365  # exclusive
    CRUDE_COLLAPSE_USD_PER_BBL: float = 15.0

    # Regulatory tightening: permanent carbon-price step on
    # `REGULATORY_DAY`, with the active-events marker tagged for the
    # `REGULATORY_DURATION_DAYS`-long regulatory window.
    REGULATORY_DAY: int = 30
    REGULATORY_DURATION_DAYS: int = 200
    REGULATORY_CARBON_PRICE_MULT: float = 2.0

    # Baseline pricing snapshots — used to restore on the window's
    # closing day. Track the defaults that World.reset writes into
    # state, so a window-end clear does not need to inspect Config.
    _BASELINE_COAL_USD_PER_MWH: float = 12.0
    _BASELINE_GAS_USD_PER_MWH: float = 30.0
    _BASELINE_CRUDE_USD_PER_BBL: float = 40.0

    def apply(self, world: World, day: int) -> None:
        state = world.state

        # Fuel-price shock. Re-write each day inside the window so a
        # mid-window /reset restores correctly; on the end day, snap
        # both back to baseline.
        if self.FUEL_SHOCK_START_DAY <= day < self.FUEL_SHOCK_END_DAY:
            state.plant_fuel_cost_per_mwh["coal_plant"] = self.FUEL_SHOCK_COAL_USD_PER_MWH
            state.plant_fuel_cost_per_mwh["gas_peaker"] = self.FUEL_SHOCK_GAS_USD_PER_MWH
            if day == self.FUEL_SHOCK_START_DAY:
                state.scenario_trace.append(
                    {
                        "day": day,
                        "kind": "fuel_shock_start",
                        "coal_usd_per_mwh": self.FUEL_SHOCK_COAL_USD_PER_MWH,
                        "gas_usd_per_mwh": self.FUEL_SHOCK_GAS_USD_PER_MWH,
                    }
                )
        elif day == self.FUEL_SHOCK_END_DAY:
            state.plant_fuel_cost_per_mwh["coal_plant"] = self._BASELINE_COAL_USD_PER_MWH
            state.plant_fuel_cost_per_mwh["gas_peaker"] = self._BASELINE_GAS_USD_PER_MWH
            state.scenario_trace.append({"day": day, "kind": "fuel_shock_end"})

        # Crude collapse — same start/clear pattern as fuel shock.
        if self.CRUDE_COLLAPSE_START_DAY <= day < self.CRUDE_COLLAPSE_END_DAY:
            state.crude_price_usd_per_bbl = self.CRUDE_COLLAPSE_USD_PER_BBL
            if day == self.CRUDE_COLLAPSE_START_DAY:
                state.scenario_trace.append(
                    {
                        "day": day,
                        "kind": "crude_collapse_start",
                        "crude_usd_per_bbl": self.CRUDE_COLLAPSE_USD_PER_BBL,
                    }
                )
        elif day == self.CRUDE_COLLAPSE_END_DAY:
            state.crude_price_usd_per_bbl = self._BASELINE_CRUDE_USD_PER_BBL
            state.scenario_trace.append({"day": day, "kind": "crude_collapse_end"})

        # Regulatory tightening — fire once on REGULATORY_DAY.
        # Permanent carbon-price step (matches the stochastic
        # sampler's semantics). The active-events marker carries the
        # configured duration so the run log shows a window; the
        # marker auto-expires via `expire_finite_events`.
        if day == self.REGULATORY_DAY:
            already = any(
                e.get("type") == "regulatory_tightening"
                and e.get("started_day") == self.REGULATORY_DAY
                for e in state.active_events
            ) or any(
                e.get("type") == "regulatory_tightening"
                and e.get("started_day") == self.REGULATORY_DAY
                for e in state.historical_events
            )
            if not already:
                carbon_before = state.carbon_price
                state.carbon_price *= self.REGULATORY_CARBON_PRICE_MULT
                state.active_events.append(
                    {
                        "type": "regulatory_tightening",
                        "started_day": day,
                        "ends_day": day + self.REGULATORY_DURATION_DAYS,
                        "severity": state.carbon_price,
                    }
                )
                state.scenario_trace.append(
                    {
                        "day": day,
                        "kind": "regulatory_tightening_injected",
                        "carbon_price_before": carbon_before,
                        "carbon_price_after": state.carbon_price,
                    }
                )
