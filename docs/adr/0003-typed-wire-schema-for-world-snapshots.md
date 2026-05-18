# Typed wire schema for `World` snapshots (supersedes ADR-0002 in spirit)

ADR-0002 said "`World` owns its wire-format dicts." The dicts in question
were three string-keyed blobs on `WorldState` (`weather_now`, `power_now`,
`today_summary_so_far`) plus three peer `last_day_*_by_hour` lists. The
"dict" part was incidental — they were dicts because that was the
cheapest shape to ship through `state_dict()` to FastAPI.

That shape leaked. Adding a new tick output meant picking a magic key
string in `sim.py`, then hoping every reader (`preview.py`, agents,
tests, the UI) spelled it the same way. The "interface" of each
snapshot was its set of magic strings — a [shallow module] in the
LANGUAGE.md sense: the interface was as complex as the implementation.

We replaced the three dicts and three lists with typed pydantic models in
`world/snapshots.py`:

- `WeatherNow` (frozen) — the four observable weather variables.
- `PowerNow` (frozen) — bus-level dispatch snapshot, including a
  `BalanceState` `StrEnum` for the previously magic-string
  `balance_state`, and a nested `BySourceKw` for the per-plant-type
  totals.
- `LastDayTrace` (mutable) — the three 24-element traces, bundled.
- `DayLedger` (mutable, `validate_assignment=False`) — the 20-field
  per-day accumulator. The `validate_assignment=False` keeps the hot
  path (`ledger.power_revenue += revenue`) a single attribute write.

`WorldState` exposes these as `weather_now`, `power_now`,
`last_day_trace`, and `today`. The accumulator was renamed from
`today_summary_so_far` because the typed model makes the verbose
qualifier redundant — the name is now what it always meant.

## What changes on the wire

`World.state_dict()` returns the pydantic models directly. FastAPI's
`jsonable_encoder` serialises them via `model_dump()`, so the JSON shape
external HTTP consumers see is unchanged in keys (with two exceptions):

- The top-level key `today_summary_so_far` becomes `today`. Affected
  readers: `world/ui/app.js`, `agents/state_summary.py`. External
  agents that read this key must update.
- `state.last_day_supply_kw_by_hour` / `state.last_day_demand_kw_by_hour`
  / `state.last_day_balance_state_by_hour` are now sourced from
  `state.last_day_trace.*` internally. The wire keys are preserved
  through explicit projection in `state_dict()` so external readers
  continue to work.

In-process callers (tests, `UiAgentApiClient`, the scripted agent
in-tree) read attributes instead of dict keys, which gives them
type-checked access and structural equality in tests.

## What didn't change

ADR-0002's thesis — that `World` owns its wire-format projection
rather than pushing it up to `api.py` — still holds. `api.py` remains
a thin pass-through. What this ADR changes is the *type* of the wire
schema: typed pydantic models instead of plain dicts. The locus of
ownership is the same.

## Why not split `DayLedger` by concern

`DayLedger` could plausibly split into `PowerLedger` / `OilLedger` /
`EmissionsLedger` / `WellLedger`. We chose the flat 1:1 mirror because
the only real concern boundary today is "things that get reset at
midnight" — splitting would invent boundaries that aren't load-bearing.
The rule of three says wait for a second axis to emerge.

[shallow module]: ../../.claude/skills/improve-codebase-architecture/LANGUAGE.md
