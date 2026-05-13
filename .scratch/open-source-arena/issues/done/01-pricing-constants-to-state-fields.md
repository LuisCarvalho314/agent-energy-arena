# 01: Pricing constants → mutable world state fields

Status: ready-for-agent

## Parent

`.scratch/open-source-arena/PRD.md`

## What to build

Promote ten pricing/rate constants — crude price, refined price, grid retail price, grid export price, industrial revenue per day, commercial revenue per resident per day, daily tax per capita, blackout penalty per hour, and the per-fuel-type plant fuel cost dict — from module-level constants to mutable fields on `world.state.WorldState`. World reset initializes each field from its existing constant (the constant stays in its original file as the documented default). Every read site (subsurface, economy, pricing helpers, population, power) now reads from state, not the constant.

This is a refactor only: no new mechanics, no new endpoints, no behavior change with default values. The byte trace of a baseline-seed scripted-agent run must be unchanged.

## Acceptance criteria

- [ ] `WorldState` exposes the ten new mutable fields (nine scalars + the per-fuel-type cost dict) with type annotations.
- [ ] World reset populates each field from the existing module-level constant defaults.
- [ ] Every read site in `subsurface.py`, `economy.py`, `pricing.py`, `population.py`, `power.py` reads from state instead of importing the constant.
- [ ] Existing dispatch, economy, refinery, tax, and blackout-penalty tests pass unchanged.
- [ ] The existing determinism test (scripted agent on seed 42 twice, byte-identical state) still passes.
- [ ] A new regression test asserts that with default state values, per-day fuel-cost accrual, refinery revenue, industrial revenue, commercial revenue, tax revenue, and blackout-penalty accrual match pre-refactor figures on a fixture world.
- [ ] `make check` passes.

## Blocked by

None — can start immediately.
