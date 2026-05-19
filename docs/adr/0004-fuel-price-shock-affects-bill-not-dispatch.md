# `fuel_price_shock` affects the bill, not the dispatch merit order

`fuel_price_shock` (gas × 2.5, coal × 1.3) multiplies the end-of-day
fuel cost in `economy.settle_fuel`. It does **not** multiply the
per-MWh figures `world.power.dispatch` reads off
`state.plant_fuel_cost_per_mwh` to order the coal-vs-gas merit stack.
The asymmetry is intentional: the shock is a financial event, not an
operational one.

If we also applied the shock to dispatch, the merit-order key for gas
peakers would jump (catalog $30/MWh × 2.5 = $75/MWh) above coal's
shocked figure ($12/MWh × 1.3 = $15.6/MWh) — a step change in
hour-to-hour generation mix on the day the shock fires. That coupling
turns one event into two: a bill shock *and* a dispatch shock. We
want the player to feel the bill in their treasury without the grid
mix shifting under them; resilience to a shock is a financial
question, not a dispatch question.

`state.plant_fuel_cost_per_mwh` exists as a separate seam for
scenarios that *do* want a dispatch effect — a scenario can rewrite
those values in its `apply(world, day)` body to flip merit order
explicitly. Events stay financial.

Consequence for the code: `event_effects.fuel_price_shock_bill_mult`
is consumed only by `settle_fuel`. Dispatch never imports it. A
future reviewer at `dispatch()` who wonders "why isn't the shock here
too" should land on this ADR via the function docstring on
`fuel_price_shock_bill_mult`.
