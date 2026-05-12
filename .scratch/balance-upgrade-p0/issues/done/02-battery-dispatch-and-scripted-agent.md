Status: needs-triage

## Parent

PRD: `.scratch/balance-upgrade-p0/PRD.md`

## What to build

Activate batteries: add charge/discharge dispatch steps, update renewable-share accounting, and teach the scripted agent to build batteries when renewables exist. After this slice, a solar-heavy fleet can cover the evening peak from stored midday surplus, manual `charge_setpoint_kw > 0` is clamped to renewable surplus, and `agents/scripted.py` produces a battery-aware baseline run.

- Two pure helpers (testable without the full `dispatch()` cascade):
  - `battery_charge_step(...)`: at dispatch position 1.5 (between must-take renewables and coal must-run). If renewable supply > demand, absorbs up to `min(surplus, rated_charge_kw, room_in_soc)` per battery, applying `sqrt(eta)` charging efficiency.
  - `battery_discharge_step(...)`: at dispatch position 5 (after gas peakers). If residual demand > 0, discharges up to `min(residual, rated_discharge_kw, soc_kwh)`, applying `sqrt(eta)` discharge efficiency.
- Auto policy when `charge_setpoint_kw == 0` (default). Manual override:
  - Positive cmd (charge) clamped to renewable surplus at step 1.5. No surplus → no charging regardless of setpoint.
  - Negative cmd (discharge) honoured at step 5 up to SoC.
- Renewable-share accounting: battery discharge counts as 100% renewable kWh in both `cumulative_renewable_served_kwh` and `cumulative_total_served_kwh`. Round-trip losses vanish from both numerator and denominator. Manual-charge clamp guarantees every kWh entering a battery is renewable.
- Scripted agent (`agents/scripted.py`): once at least one solar farm or wind turbine exists, build 2–4 batteries. Sizing: one battery per 2 renewable plants, capped at 4. Built only when treasury permits the full $60k.

## Acceptance criteria

- [ ] Unit tests for `battery_charge_step`: charges from surplus, respects rated power, respects SoC cap, applies `sqrt(eta)`, no-op when supply ≤ demand, clamps manual positive setpoint to surplus.
- [ ] Unit tests for `battery_discharge_step`: closes residual demand, respects rated power and SoC floor, applies `sqrt(eta)`, no-op when residual = 0.
- [ ] Integration in `test_dispatch.py`:
  - `test_battery_charges_during_curtailment`
  - `test_battery_discharges_to_avoid_brownout`
  - `test_battery_round_trip_loses_15_percent` (1 kWh in, ~0.85 kWh out)
- [ ] `test_control_battery_manual_charge_clamped_to_renewable_surplus` (API + dispatch).
- [ ] Renewable-share numerator and denominator both include battery discharge kWh.
- [ ] Scripted agent builds 2–4 batteries on a seed where solar/wind exists and treasury allows.
- [ ] Battery dispatch consumes no RNG; replay determinism preserved.
- [ ] `make check` passes.

## Blocked by

- `01-battery-tile-and-control-endpoint.md`
