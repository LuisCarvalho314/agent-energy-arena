# 03 — Rate-based pressure: physics + sim

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Replace the cumulative-injection pressure term with a rate-based one. Each producer's `pressure_boost` is `min(0.5, Σ qualifying yesterday_inj_rate / max(yesterday_prod_rate, 1.0))`, where qualifying injectors share the producer's `reservoir_id` and sit at Chebyshev distance > 1 from the producer's target (no breakthrough). Yesterday's rates are a per-day snapshot taken at the start of `_advance_one_day`. No state-dict or UI changes in this slice (issue 04 covers observability).

## Acceptance criteria

- [ ] `Well` gains `yesterday_rate_bbl_day: float`, initialised to 0.0.
- [ ] `world/sim.py:_advance_one_day` snapshots `well.yesterday_rate_bbl_day = well.current_rate_bbl_day` for every well at the start of the day, before any production/injection computation.
- [ ] `well_production_bbl_day` signature changes: replaces `inj_total_bbl: float` with `qualifying_inj_rate_bbl_day: float` and `producer_yesterday_rate_bbl_day: float`. The pressure term becomes `min(0.5, qualifying_inj_rate / max(producer_yesterday_rate, 1.0))`.
- [ ] Sim production loop replaces the `pools_intersect` aggregation with: for each producer, sum `yesterday_rate_bbl_day` over injectors that have the same `reservoir_id` AND Chebyshev distance > 1 from the producer's target. Pass that sum + the producer's own `yesterday_rate_bbl_day` into `well_production_bbl_day`.
- [ ] On the day a well is drilled, `yesterday_rate_bbl_day` stays at 0 → `pressure_boost = 0` that day.
- [ ] `pools_intersect` stays in `world/subsurface.py` as dead code (no caller); the `inj_total` aggregation in sim is removed. `cumulative_injected_bbl` stays on `Well` as telemetry only.
- [ ] `world/tests/test_production.py` / `test_injection.py` extended:
  - [ ] Drilling a producer with no injector → `pressure_boost = 0`.
  - [ ] Same-reservoir producer + injector at Chebyshev 2 → `pressure_boost > 0` starting day 2 (day 1 still 0 due to cold start).
  - [ ] Same-reservoir producer + injector at Chebyshev 1 → `pressure_boost = 0` (breakthrough gate).
  - [ ] Producer + injector in different reservoirs → `pressure_boost = 0`.
  - [ ] Idling an injector (setpoint = 0) for one day → `pressure_boost` drops to 0 the day after.
  - [ ] Two qualifying injectors → their `yesterday_rate_bbl_day` sums in the numerator.
  - [ ] Cap: high inj_rate / low prod_rate → `pressure_boost` capped at 0.5.
- [ ] `make check` passes (existing tests that pinned cumulative-based pressure values must be updated to the new formula).

## Blocked by

- `.scratch/oilfield-v2/issues/01-bfs-reservoirs.md`
