# API

The FastAPI server in `world/api.py` is the single source of truth. Every endpoint shape below is exactly what an agent author talks to, regardless of transport (live HTTP via `httpx`, or in-process `TestClient`). The Python wrapper `agents.api_client.ApiClient` is a one-to-one mirror — if you prefer not to roll your own HTTP, use it.

The default base URL is `http://localhost:8000`. Run `make serve` (or `docker compose up`) to bring the server up.

## Conventions

All mutating endpoints return a common envelope:

```json
{
  "ok": true | false,
  "error": "string?",
  "treasury_after": 432100.5,
  "result": { /* endpoint-specific payload, only on ok=true */ }
}
```

- `ok: false` means the call was rejected; **no state change** occurred and `error` is a short machine-readable token (`insufficient_funds`, `tile_occupied`, …).
- `ok: true` means the action applied and `result` carries the endpoint-specific payload.

Read endpoints return the payload directly (no `ok` envelope). HTTP 4xx is reserved for **input validation** (bad path, missing required field, out-of-range parameter) and surfaces through the FastAPI/Pydantic layer; gameplay-level failures (`insufficient_funds`, `no_road_adjacency`) come back as `ok: false` with HTTP 200.

Every mutating call is appended to `runs/{run_id}/actions.jsonl`, even when `ok: false`. End-of-day snapshots land in `runs/{run_id}/states.jsonl`; score a recorded run offline with `python evaluate.py --score runs/{run_id}`.

## Endpoint index

State & metadata: [`/state`](#get-state) · [`/state/history`](#get-statehistory) · [`/actions`](#get-actions) · [`/scenario`](#get-scenario) · [`/scenarios`](#get-scenarios) · [`/run`](#get-run) · [`/seed`](#get-seed) · [`/catalog`](#get-catalog) · [`/events`](#get-events) · [`/score`](#get-score) · [`/forecast`](#get-forecast) · [`/reservoirs`](#get-reservoirs)

Mutations: [`/reset`](#post-reset) · [`/scenario`](#post-scenario) · [`/step`](#post-step) · [`/build`](#post-build) · [`/demolish`](#post-demolish) · [`/survey`](#post-survey) · [`/drill`](#post-drill) · [`/control/well`](#post-controlwell) · [`/control/battery`](#post-controlbattery) · [`/control/refinery`](#post-controlrefinery)

Agent Play (UI attach mode): [`/agent`](#agent-play-endpoints) · [`/agent/folders`](#agent-play-endpoints) · [`/agent/attach`](#agent-play-endpoints) · [`/agent/detach`](#agent-play-endpoints)

---

## State and metadata

### `GET /state`

Returns the full world snapshot.

```json
{
  "seed": 42,
  "day": 145,
  "hour": 0,
  "treasury": 432100.50,
  "population": 1230,
  "employed": 980,
  "unemployed": 250,
  "housing_capacity": 1480,
  "jobs_total": 1100,
  "jobs_vacant": 120,
  "happiness": 0.85,
  "config": {
    "world_w": 32, "world_h": 32, "world_d": 16,
    "game_days": 3650, "manual_game_days": 365, "ticks_per_day": 24,
    "carbon_price": 25.0, "starting_cash": 500000, "starting_pop": 100,
    "session": "agent",
    "active_game_days": 3650,
    "ui_play_ms": 1000, "ui_fast_play_ms": 200
  },
  "tiles": [
    {
      "id": "tile_42", "type": "solar_farm",
      "x": 12, "y": 8, "built_day": 23,
      "operational": true, "current_output_kw": 95.2
    }
  ],
  "wells": [
    {
      "id": "well_3", "type": "production",
      "x": 5, "y": 14, "target_z": 8, "drilled_day": 67,
      "setpoint_rate_bbl_day": 150, "current_rate_bbl_day": 122.4,
      "cumulative_produced_bbl": 8542.1
    }
  ],
  "reservoirs_revealed": {...},
  "reservoirs_summary": [...],
  "active_events": [
    {"type": "heatwave", "started_day": 142, "ends_day": 147, "severity": 1.4}
  ],
  "historical_events": [...],
  "regulatory_tightenings_applied": 0,
  "weather_now": {
    "solar_irradiance": 0.78, "wind_speed_mps": 8.2,
    "wind_direction_deg": 145, "cloud_factor": 0.91
  },
  "power_now": {
    "demand_kw": 1840, "supply_kw": 1880, "balance_state": "balanced",
    "by_source_kw": {"solar": 320, "wind": 410, "gas": 800, "coal": 350}
  },
  "last_day_supply_kw_by_hour": [...],
  "last_day_demand_kw_by_hour": [...],
  "last_day_balance_state_by_hour": [...],
  "next_24h_preview": [...],
  "today": {...},
  "cumulative_renewable_served_kwh": 1234567.0,
  "cumulative_total_served_kwh": 2345678.0,
  "pipeline_networks": [...],
  "orphan_well_ids": [],
  "orphan_refinery_ids": []
}
```

`config.active_game_days` is the cap your day loop should stop at — `game_days` in the agent (`session=agent`) session, `manual_game_days` in the UI (`session=manual`) session.

Errors: none.

### `GET /state/history`

Query: `day` (int, required). Reads one recorded end-of-day snapshot from the in-progress run's `states.jsonl` — a read-only "peek backward" that does not move simulation state. Live `state.day == N` means the most recent recorded entry is `day == N - 1`.

Errors: `404` if there is no recorder, no `states.jsonl`, or `day` is not in the recorded history.

### `GET /actions`

Query: `day` (int, required). Line-scans the in-progress run's `actions.jsonl` and returns the slice of successful actions whose day-range contains `day` (the slice between the surrounding `/step` / `/reset` boundaries). Powers the UI Actions panel.

```json
{ "day_start": 7, "day_end": 13, "entries": [ { "endpoint": "/build", "params": {...}, "ok": true, "result": {...} }, ... ] }
```

Returns an empty slice (`{"day_start": day, "day_end": day, "entries": []}`) when no `actions.jsonl` exists yet.

### `GET /scenario`

```json
{
  "dotted_path": "scenarios.grid_stress",
  "description": "Grid-stress scenario — sustained low-wind weeks + heatwave cluster.",
  "source": "from __future__ import annotations\n..."
}
```

`dotted_path` is `null` (and `description`/`source` are `null`) when no scenario is attached (the default `NullScenario`). `description` is the scenario class docstring; `source` is the full module source the UI renders in a read-only code box.

### `GET /scenarios`

Discovers the dotted paths of every `Scenario` subclass under `scenarios/`. Powers the UI scenario picker.

```json
{ "scenarios": ["scenarios.baseline", "scenarios.economy_stress", "scenarios.grid_stress"] }
```

### `GET /run`

```json
{ "run_id": "20260513-153219-1A2B", "dir": "runs/20260513-153219-1A2B" }
```

Returns `{"run_id": null, "dir": null}` when the world has no recorder attached (test/in-process callers may opt out).

### `GET /seed`

```json
{ "seed": 42 }
```

### `GET /catalog`

Returns the machine-readable build catalog. Shape:

```json
{
  "tiles": [
    {"tile_type": "house", "capex": 3000, "opex_per_day": 20, "requires_road": true,
     "description": "...", "housing_capacity": 8, "jobs": 0, "demand_kw": 0,
     "capacity_kw": 0, "fuel_cost_per_mwh": 0, "co2_t_per_mwh": 0,
     "storage_kwh": 0, "round_trip_efficiency": 0, "buildable": true},
    ...
  ],
  "wells": [{"tile_type": "oil_well", "capex": 50000, "buildable": false, ...}, ...],
  "subsurface": {
    "survey": {
      "base_cost": 15000, "base_size": 4, "min_size": 4, "max_size": 16,
      "cost_formula": "base * (size/4)**2", "default_size": 4
    },
    "drill": {
      "production": {"capex": 50000, "opex_per_day": 100, "max_rate_bbl_day": 200,
                     "crude_price_usd_per_bbl": 40.0,
                     "cost_formula": "base * (1 + (target_z / world_depth)**2)", "world_depth": 16},
      "injection": {"capex": 30000, "opex_per_day": 50, "max_rate_bbl_day": 200,
                    "kwh_per_bbl": 50.0,
                    "cost_formula": "base * (1 + (target_z / world_depth)**2)", "world_depth": 16}
    }
  },
  "economics": {
    "industrial_revenue_per_day": 500.0,
    "commercial_revenue_per_resident_per_day": 2.0,
    "commercial_radius": 2,
    "carbon_price": 25.0,
    "grid_price_retail": 0.08, "grid_price_export": 0.04,
    "refined_price_usd_per_bbl": 90.0,
    "refinery_yield": 0.85, "refinery_co2_t_per_bbl": 0.3, "refinery_max_bbl_day": 250.0,
    "crude_price_usd_per_bbl": 40.0,
    "injection_kwh_per_bbl": 50.0
  }
}
```

The `tiles` / `wells` entries are the full `TileSpec` (only `wells` carry `buildable: false`). Use this rather than hardcoding numbers — re-tunes land here automatically. (Illustrative values above; the live `economics` numbers come from `world/economy.py`.)

### `GET /events`

```json
{
  "active": [{"type": "heatwave", "started_day": 142, "ends_day": 147, "severity": 1.4}],
  "historical": [...],
  "regulatory_tightenings_applied": 0
}
```

### `GET /score`

Trend-aware absolute score in `[0, 100]`, computed from the active recorder's per-day `states.jsonl` on disk (the in-memory state is deliberately not consulted, so mid-game queries work by construction).

```json
{
  "n_days": 365,
  "score": 62.4,
  "components": {
    "level_treasury": 0.71, "trend_treasury": 0.55, "trough_treasury": 0.40, "axis_treasury": 0.58,
    "level_pop": 0.66, "trend_pop": 0.60, "trough_pop": 0.48, "axis_pop": 0.60,
    "level_happy": 0.80, "trend_happy": 0.50, "trough_happy": 0.62, "axis_happy": 0.66,
    "R": 0.84, "renewable_share": 0.42, "solvency": 1.0
  }
}
```

Each of treasury / population / happiness decomposes into a level/trend/trough triple, weighted into a per-axis utility; the headline blends the three axes with a renewable-share term (`R`) and a solvency term. A missing recorder, missing file, or empty file all return `{"n_days": 0, "score": 0.0, "components": {}}` with HTTP 200 (never 404), so polling clients use one code path. See `world/scoring.py` for the formula and scale anchors.

### `GET /forecast`

Query: `hours` (1–168, default 24).

```json
[
  {"hour_offset": 0, "solar_irradiance": 0.78, "wind_speed_mps": 8.2, "demand_factor": 1.02, "sigma": 0.05},
  ...
]
```

`sigma` is the noise scale applied at that horizon (grows with `hour_offset`). Forecasts are noisy and re-sampled per call — re-querying reduces variance via averaging.

Errors: `400` if `hours` is out of `[1, 168]`.

### `GET /reservoirs`

Query: `min_oil` (float ≥ 0, default 0), `top_k` (1–4096, default 100). Returns the voxels ever revealed by surveys, filtered and sorted by current oil estimate.

```json
{
  "voxels": [
    {
      "x": 5, "y": 14, "z": 8, "reservoir_id": "res_2",
      "oil_estimate_bbl": 18250, "perm_estimate_md": 412,
      "survey_day": 60, "n_surveys": 2
    }
  ],
  "n_returned": 100,
  "filter": {"min_oil": 0.0, "top_k": 100}
}
```

Voxels are ranked by latest `oil_estimate_bbl × perm_estimate_md` descending. Estimates carry survey noise; re-surveying a column appends a fresh reading (`n_surveys` grows) and the latest one is reported.

Errors: `400` if `top_k` is out of `[1, 4096]`.

---

## Mutations

### `POST /reset`

Body: `{ "seed": int?, "scenario": "dotted.path"? }`.

```json
// → 200
{
  "ok": true,
  "treasury_after": 500000.0,
  "result": { "seed": 42, "day": 0 }
}
```

- `seed` omitted: reuse the configured `WORLD_SEED` (env or 42).
- `scenario` omitted: keep whatever scenario is currently attached (typically `NullScenario`).
- `scenario` set: must be a dotted module path importable from `PYTHONPATH` and exposing a `Scenario` subclass.

A reset finalizes the in-progress recorder run (writing `final_state.json`) and allocates a fresh `run_id`. The action log rebinds to the new run folder. Any agent attached via `POST /agent/attach` is auto-detached; the active scenario is preserved unless `scenario` is supplied.

Errors:

- `400 could not import scenario module ...` — bad dotted path or import error.
- `400 module ... does not define a Scenario subclass` — module imported but has no `Scenario` subclass.

### `POST /scenario`

Body: `{ "dotted_path": "scenarios.grid_stress" }`.

```json
// → 200
{ "ok": true, "dotted_path": "scenarios.grid_stress" }
```

Attaches the scenario mid-game without resetting. Subsequent `POST /step` calls invoke the new scenario's `apply(world, day)` hook. The call is captured in the action log so a replay reproduces the attach.

Errors: same as `POST /reset` for scenario-resolution issues.

### `POST /step`

Body: `{ "days": int }` (1–7, default 7).

```json
{
  "ok": true,
  "day_completed": 145,
  "summary": {
    "treasury_start": 430850.00,
    "treasury_end":   432100.50,
    "delta":            1250.50,
    "population_start": 1228,
    "population_end":   1230,
    "happiness":        0.85,
    "events_active":    ["heatwave"]
  },
  "treasury_after": 432100.50
}
```

`day_completed` is the last simulated day; on `days > 1` the summary's `*_start` fields span the whole window while `treasury_end` / `population_end` / `happiness` reflect the final day. The full per-day P&L breakdown (revenue by source, opex, fuel, carbon, kWh served) lives in `state.today` (see `GET /state`) and in each `runs/{run_id}/states.jsonl` line, written for every stepped day.

Errors: `400` if `days` is out of `[1, 7]`.

When an agent is attached via `POST /agent/attach`, `/step` first calls the agent's `act(state)` before advancing (honoring its skip cooldown); if `act` raises, the call returns `500` with the exception in `detail` and the day does not advance.

### `POST /build`

Body: `{ "tile_type": "solar_farm", "x": 4, "y": 4 }`.

On success `result` is the full tile view (same shape as an entry in `/state.tiles`):

```json
{
  "ok": true, "treasury_after": 475000.0,
  "result": { "id": "solar_farm-3", "type": "solar_farm", "x": 4, "y": 4,
              "built_day": 145, "operational": true, "capex_paid": 25000.0, ... }
}
```

Errors (returned as `ok: false`):

- `unknown_tile_type` (also covers non-buildable types like wells / town hall) · `out_of_bounds` · `tile_occupied`
- `no_road_adjacency` · `spacing_violation` (result carries the offending tile's `{x, y}`) · `insufficient_funds`

### `POST /demolish`

Body: `{ "x": 4, "y": 4 }`.

```json
{
  "ok": true, "treasury_after": 481250.0,
  "result": { "demolished_id": "solar_farm-3", "type": "solar_farm", "x": 4, "y": 4, "refund": 6250.0 }
}
```

Refunds 25% of the original CAPEX paid for that tile. The town hall is immutable.

Errors: `out_of_bounds` · `no_tile` · `cannot_demolish_townhall` · `would_disconnect` (removing this road would strand road-dependent tiles; `result.stranded` lists them as `{x, y, type}`).

### `POST /survey`

Body: `{ "x": 10, "y": 10, "size": 8 }` (size 4–16, default 4, quadratic cost `15000 * (size/4)²`).

```json
{
  "ok": true, "treasury_after": 485000.0,
  "result": {
    "x": 10, "y": 10, "size": 8, "cost": 60000.0,
    "voxels": [
      {"x": 10, "y": 10, "z": 0, "oil_estimate_bbl": 0, "perm_estimate_md": 0},
      ...
    ]
  }
}
```

The `voxels` array is the full surveyed `size × size × depth` column with noisy per-voxel estimates. The action log strips the array and keeps only `n_voxels` to avoid bloat; re-read `/reservoirs` to query revealed voxels later.

Errors: `out_of_bounds` · `invalid_size` · `insufficient_funds`.

### `POST /drill`

Body: `{ "x": 10, "y": 10, "target_z": 8, "well_type": "production" }`. `well_type` is `"production"` or `"injection"`.

On success `result` is the full well view (same shape as an entry in `/state.wells`):

```json
{
  "ok": true, "treasury_after": 435000.0,
  "result": { "id": "production-1", "type": "production", "x": 10, "y": 10, "target_z": 8,
              "reservoir_id": "res_2", "drilled_day": 67, "setpoint_rate_bbl_day": 0.0, ... }
}
```

Drill cost scales with depth: `capex * (1 + (target_z / world_depth)²)`. Stacked completions at the same `(x, y)` are allowed only when the drainage cubes don't overlap (`|Δtarget_z| ≥ 3`).

Errors: `invalid_well_type` · `out_of_bounds` · `voxel_out_of_bounds` · `tile_occupied` · `completion_overlap` · `insufficient_funds`.

### `POST /control/well`

Body: `{ "well_id": "well_3", "rate_bbl_day": 180 }`. Clamped to `[0, 200]`.

```json
{ "ok": true, "treasury_after": 432100.5,
  "result": { "well_id": "well_3", "setpoint_rate_bbl_day": 180.0 } }
```

Out-of-band rates are silently clamped (not rejected), so the call succeeds with the clamped value.

Errors: `unknown_well`.

### `POST /control/battery`

Body: `{ "tile_id": "tile_42", "charge_kw": 100 }`. Positive charges, negative discharges, 0 returns to auto policy. The 200 kW battery clamps charge/discharge to `[-200, +200]` in dispatch.

```json
{ "ok": true, "treasury_after": 432100.5,
  "result": { "tile_id": "tile_42", "charge_setpoint_kw": 100.0, "soc_kwh": 540.0 } }
```

Errors: `unknown_battery` (no tile with that id, or the tile is not a battery).

### `POST /control/refinery`

Body: `{ "refinery_id": "tile_55", "rate_bbl_day": 200 }`. Clamped to `[0, REFINERY_MAX_BBL_DAY]` (250 by default); out-of-band rates are clamped, not rejected.

```json
{ "ok": true, "treasury_after": 432100.5,
  "result": { "refinery_id": "tile_55", "setpoint_rate_bbl_day": 200.0 } }
```

Errors: `unknown_refinery` (no tile with that id, or the tile is not a refinery).

---

## Agent Play endpoints

These back the UI's "Agent Play" mode — attaching a participant's agent folder so the server drives it on each `/step`. CLI evaluation (`python evaluate.py --agent ...`) does not need them; it instantiates the agent in-process.

### `GET /agent`

```json
{ "folder": "agents/scripted" }
```

`folder` is the repo-relative folder of the attached agent, or `null` when none is attached.

### `GET /agent/folders`

Walks the repo for folders containing an `agent.py`, for the UI's attach dropdown.

```json
{ "folders": ["agents/langgraph_agent", "agents/llm_react", "agents/scripted"] }
```

### `POST /agent/attach`

Body: `{ "folder": "agents/scripted" }`. Loads `agent.py` from that folder (a plain folder name, **not** a Python dotted path) and instantiates its `Agent` class / `BaseAgent` subclass. Re-attach hot-reloads edits to `agent.py` and its sibling modules.

```json
{ "ok": true, "folder": "agents/scripted" }
```

Errors: `400` for a folder containing `.`, a path resolving outside the repo, a missing directory, a missing `agent.py`, or any import / construction failure (the exception is echoed in `detail`).

### `POST /agent/detach`

No body. Idempotent.

```json
{ "ok": true, "folder": null }
```

---

## Worked example

A one-day flow as an agent author might write it (using `agents.api_client.ApiClient`):

```python
from agents.api_client import ApiClient

api = ApiClient("http://localhost:8000")
api.reset(seed=42, scenario="scenarios.grid_stress")

state = api.state()
forecast = api.forecast(hours=24)

api.survey(x=10, y=10, size=8)
api.build("solar_farm", x=4, y=4)
api.control_well("well_3", rate_bbl_day=180)

summary = api.step(days=1)
print(summary["summary"]["renewable_share"])
```

For the raw HTTP transport, every method on `ApiClient` corresponds 1:1 to an endpoint above; `_get`/`_post` use `httpx` under the hood.

## Static UI

The world also serves the manual-play UI:

- `GET /` — `world/ui/index.html`
- `GET /ui/*` — static assets, served with `Cache-Control: no-store` so dev-server edits take effect on reload.

The UI is a thin client over this same API; nothing it does is unavailable to agents.
