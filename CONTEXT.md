## Language

**World**:
The deterministic simulator. Owns the day loop, RNG streams, and the
authoritative mutable game state. The `World` class also exposes the methods
the API surface calls (`build`, `drill`, `step`, `state_dict`, …).
_Avoid_: Game, Simulation, Engine

**Tile**:
A surface-grid object on the 2D city plane (house, road, plant, refinery,
industrial, commercial, town hall, battery, pipeline). Lives in
`state.tiles`. Has a `type`, `(x, y)`, and operational state.
_Avoid_: Building, Cell, Square

**Well**:
A subsurface object completed in a voxel `(x, y, target_z)`. Either a
**production** well (lifts crude) or an **injection** well (pumps water to
boost reservoir pressure). Lives in `state.wells`.
_Avoid_: Borehole, Drill site

**hourly_tick**:
One hour of simulated World time. A day is `ticks_per_day` (=24) hourly
ticks. Each tick determines this hour's demand (civilian load + injection /
production well power draw + refinery process load), runs plant `dispatch`
against that demand with one-hour-lagged DR, applies battery
charge/discharge, computes the bus-level balance state, and yields the
`prev_outputs`/`prev_balance` carried into the next tick. The tick is the
unit shared between `World.step` (advances and mutates) and
`world.preview.preview_next_day` (read-only projection of the next 24
ticks). `hourly_tick` is pure — it returns a `TickResult` and never
mutates state. Sim calls `commit_tick` to write the result to state;
preview discards it.
_Avoid_: Step (reserved for `World.step`, which advances ≥ 1 day), Update,
Frame

**commit_tick**:
The sim-only mutating peer of `hourly_tick`. Takes a `TickResult` and
applies every per-hour mutation to `WorldState`: battery SoC clamping,
outage bookkeeping (`today.blackout_hours`, `today.blackout_penalty`),
power revenue accrual, renewable-share accumulators, per-well injection
and production commits, by-source kWh running totals, per-plant
`current_output_kw` and `kwh_served_today`, `PowerNow` snapshot, and the
hourly traces (`supply_kw`, `demand_kw`, `balance_state`) on
`state.today`. Preview never calls `commit_tick`. The split is what makes
preview/sim drift-impossible: both call the same `hourly_tick`; only sim
commits.
_Avoid_: apply_tick, settle_tick, record_tick

**state_view**:
The external dict shape `World` returns to API consumers (UI, agent
clients, tests) for a single `Tile` or `Well`. Distinct from the domain
object: dicts carry the same identity plus derived popup fields (estimated
revenue, CO2, fuel/carbon cost, net). Produced by `tile_view` / `well_view`
in `world/state_view.py`. Used inside `World.build`, `World.drill`, and
`World.state_dict`.
_Avoid_: Serialized tile, Tile DTO, Wire format

**DayLedger**:
The per-day bookkeeping pydantic model on `WorldState.today` (was the
dict `today_summary_so_far`). Holds two kinds of fields, both reset at
the top of each day by `_advance_one_day`:

  - **Rollups** — float fields summed across the day's 24 hourly ticks
    plus end-of-day phases (`power_revenue`, `opex`, `fuel_cost`,
    `co2_emitted_t`, `blackout_hours`, `blackout_penalty`, ...). The
    day's `treasury` delta is derived from these.
  - **Per-hour accumulators** — dict/list fields populated by
    `commit_tick` across the 24 ticks and consumed by end-of-day phases
    (`inj_bbl_by_well`, `prod_kwh_by_well`, `coal_kwh_running`,
    `gas_kwh_running`, `supply_kw_by_hour`, `demand_kw_by_hour`,
    `balance_state_by_hour`). At end-of-day, the per-hour traces are
    copied to `LastDayTrace` and `DayLedger.reset()` clears everything.

`validate_assignment=False` keeps the hot path (`ledger.field +=`) a
single attribute write. Lives in `world/snapshots.py`.
_Avoid_: today_summary, day_summary, accumulator dict

**PowerNow** / **WeatherNow** / **LastDayTrace**:
Frozen pydantic snapshots on `WorldState`. `PowerNow` and `WeatherNow`
are whole-value replaced each hourly_tick — never mutated in place;
`LastDayTrace` holds the 24-element supply/demand/balance traces for
the most recently completed day, surfaced on the UI power tab. Lives
in `world/snapshots.py`.
_Avoid_: power dict, weather dict, snapshot dict

**BalanceState**:
The four bus-level dispatch outcomes: `BALANCED`, `BROWNOUT`,
`BLACKOUT`, `CURTAILMENT`. A `StrEnum` (JSON-serialises as its string
value), so it stays human-readable on the wire while giving in-process
callers type-checked comparison. Lives in `world/snapshots.py`.
_Avoid_: grid_state, dispatch_outcome, balance string

## Relationships

- A **World** contains many **Tiles** and many **Wells**.
- A **World**'s day is `ticks_per_day` **hourly_tick**s; `World.step`
  advances them and mutates state, while `preview_next_day` simulates the
  next 24 ticks without mutation.
- `World.state_dict()` returns a snapshot that includes one **state_view**
  per **Tile** and per **Well**.
- **state_view** dicts compose values from `world/pricing.py` (per-facility
  economics) — the popup row and the city-wide aggregator share those
  helpers as a single source of truth.
- A **World** exposes one **PowerNow**, one **WeatherNow**, one
  **LastDayTrace**, and one **DayLedger** through `state.power_now`,
  `state.weather_now`, `state.last_day_trace`, `state.today`. All four
  are pydantic models (typed wire schema per ADR-0003).
