Status: needs-triage

## Parent

PRD: `.scratch/balance-upgrade-p0/PRD.md`

## What to build

Make batteries a first-class buildable tile end-to-end, but inert (no dispatch participation yet). After this slice, an agent can `/build battery`, see per-tile `soc_kwh` and `charge_setpoint_kw` in `/state`, and call `POST /control/battery` to set a setpoint. Battery has no effect on dispatch.

- New `TileSpec` for `battery`: capex $60k, opex $40/day, `capacity_kw=200` (rated charge/discharge power), `storage_kwh=800`, `round_trip_efficiency=0.85`, `requires_road=False`, `jobs=0`. Add `storage_kwh` and `round_trip_efficiency` fields to `TileSpec` (only used by battery).
- New `Tile` fields: `soc_kwh: float = 0.0` and `charge_setpoint_kw: float = 0.0`. Initialised to 0 on build and on `/reset`.
- `/state` per-tile dict exposes `soc_kwh` (raw kWh, not fraction) and `charge_setpoint_kw` for battery tiles. Mirrors the well precedent.
- New endpoint `POST /control/battery {tile_id: str, charge_kw: float}`. Sets `tile.charge_setpoint_kw` and returns the updated tile state. Positive = charge, negative = discharge, 0 = auto.
- Catalog endpoint exposes battery `TileSpec` like any other buildable tile.

## Acceptance criteria

- [ ] Agent can `POST /build` a battery with $60k from treasury; tile appears with `soc_kwh=0` and `charge_setpoint_kw=0`.
- [ ] `/state` response includes `soc_kwh` and `charge_setpoint_kw` for each battery tile (`test_state_response_includes_soc_kwh_per_battery`).
- [ ] `POST /control/battery` with `charge_kw=50` sets the setpoint and returns updated tile (`test_control_battery_endpoint_sets_setpoint`).
- [ ] `/reset` clears `soc_kwh` and `charge_setpoint_kw` back to 0.
- [ ] `workforce.efficiency(battery) == 1.0` (passive tile branch, `jobs=0`).
- [ ] `make check` passes.

## Blocked by

None - can start immediately.
