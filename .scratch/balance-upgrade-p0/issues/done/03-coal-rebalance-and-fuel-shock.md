Status: needs-triage

## Parent

PRD: `.scratch/balance-upgrade-p0/PRD.md`

## What to build

Reposition coal as the cheap baseload anchor and split fuel-shock / plant-failure exposure per fuel type, so a fleet-size regime exists where coal beats gas and operational reliability rewards baseload. The per-plant RNG draw cadence in `events.sample_and_apply_events` is preserved — only per-type thresholds change.

- `coal_plant` `capacity_kw`: 800 → 1500.
- `coal_plant` `fuel_cost_per_mwh`: 20 → 12.
- Replace single `FUEL_PRICE_SHOCK_MULT = 2.0` with `GAS_FUEL_SHOCK_MULT = 2.5` and `COAL_FUEL_SHOCK_MULT = 1.3`.
- Change signature: `fuel_price_shock_multiplier(state)` → `fuel_price_shock_multiplier(state, fuel_type)`. Update callers in `economy.py` (and anywhere else) to pass plant type.
- Split plant-failure probabilities per type: `PLANT_FAILURE_PROB = {"gas_peaker": 0.0014, "coal_plant": 0.0006}`. Preserve per-plant roll loop in id-ascending order — one draw per fossil plant per day. Only the threshold differs per type. Average stays near 0.001/day.

## Acceptance criteria

- [ ] `test_coal_cheaper_per_mwh_than_gas_at_default_carbon` in `test_dispatch.py`.
- [ ] `test_fuel_shock_hits_gas_harder` in `test_events.py`.
- [ ] `test_plant_failure_samples_gas_more_often_over_n_trials` in `test_events.py` (Monte Carlo N=10000, gas/coal ratio matches ~0.0014/0.0006 within tolerance).
- [ ] Fleet-size scaling preserved: 10-plant fleet sees ~10× the failure rate of a 1-plant fleet.
- [ ] Replays on seed 42 byte-identical modulo the threshold change (same number of RNG draws per day).
- [ ] `make check` passes.

## Blocked by

None - can start immediately.
