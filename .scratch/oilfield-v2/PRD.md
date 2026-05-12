# PRD: Oilfield mechanics v2 — connected reservoirs, rate-based pressure, depth costs, survey scaling, pipelines

Status: needs-triage

## Problem Statement

The oil side of the simulation is mechanically thin in ways that drain the game of meaningful decisions:

1. **Reservoirs are not identifiable entities.** The generator drops 3–7 blobs of HC voxels, but a per-cell stochastic roll means each blob may have holes, fragments, and disconnected slivers. A surveyed cross-section shows a soup of revealed voxels with no semantic grouping. The player cannot point to "this reservoir" and reason about it.
2. **Pressure is decoupled from current operations.** `pressure_boost` is computed from each injection well's *lifetime* `cumulative_injected_bbl`. An injector that ran one day a year ago contributes the same as one running today. The player has no way to actively manage reservoir pressure, and an idle injector is indistinguishable from a working one.
3. **Well placement within a reservoir is undermotivated.** The current geometric `pools_intersect` rule (3×3×3 pool overlap) gives a coarse "same-pool" gate but ignores reservoir identity. An injector in a *different* blob whose pool happens to overlap a producer's pool still contributes pressure. The player gets no signal that drilling should respect reservoir boundaries.
4. **Drilling depth has no economic weight.** All wells cost a flat `$50k` / `$30k` regardless of `target_z`. The brief §16 lists depth-dependent drilling cost as a v1 non-goal, but the absence collapses depth into a non-decision — agents pick the deepest oily voxel they can find without trade-off.
5. **Survey pricing is too forgiving.** The current `15_000 · (size/8)²` makes a default 8-voxel-wide survey cost $15k; agents can blanket the map cheaply. Exploration is not a strategic resource.
6. **Pipelines are decoration.** The `pipeline` tile exists in the catalog at $2k CAPEX / $5/d OPEX but no module reads it. Crude flows globally from any production well to any refinery, regardless of where they are on the 32×32 grid. Players who carefully co-locate wells and refineries get no benefit; players who drill across the map pay no transport friction.

Together these gaps reduce the oil track to "drill the highest-`k·V` voxel you can find, run it at max, build a refinery anywhere." The strategic surface area the brief promised — managing a reservoir as a depletable resource, balancing injection against extraction, paying for spatial reach — is not present.

## Solution

A bundled refactor of the subsurface and crude-economy mechanics that turns the oil track into a genuine spatial-and-rate planning problem.

1. **Connected reservoirs.** Replace the per-cell stochastic generator with BFS percolation from each blob's seed voxel using 26-connectivity. Each accepted voxel must have at least one already-accepted neighbor in the 3×3×3 cube, so each blob is connected-by-construction. Tag every HC voxel with a `reservoir_id`. Two blobs that happen to spawn adjacent stay as separate reservoirs (own `reservoir_id`, no pressure transmission across the seam).

2. **Rate-based pressure with same-reservoir + breakthrough gate.** Replace the cumulative-injection pressure term with a per-producer aggregation over qualifying injectors:
   - Same `reservoir_id` as the producer.
   - Chebyshev distance between injector target and producer target strictly greater than 1 (injector outside producer's 3×3×3 pool — avoids breakthrough).
   - `pressure_boost = min(0.5, Σ qualifying yesterday_inj_rate / max(yesterday_prod_rate, 1.0))`.
   - On the day a well is drilled, "yesterday's rate" is 0; pressure_boost = 0 that day.

3. **Quadratic-in-depth drilling cost.** `capex(z) = base · (1 + (target_z / WORLD_D)²)` for both production and injection wells, using each type's own base. At max depth z=15 a producer costs ~$94k vs flat $50k; at the shallowest reservoir depth z=4 the premium is ~6%. Modest gradient that makes depth a tiebreaker, not a wall.

4. **Quadratic survey cost rescaling.** Change scaler from `(size/8)²` to `(size/4)²`. Base $15k unchanged. UI default size drops from 8 to 4 so the first-click sticker shock matches the old default cost ($15k). A size-8 survey now costs $60k. Exploration becomes a strategic resource.

5. **Pipelines that actually connect.** Crude only reaches refineries through a 4-connected pipeline network. A production well "ships" if it has an orthogonal pipeline neighbor; a refinery "receives" if it has an orthogonal pipeline neighbor; a well-refinery pair is "linked" iff their adjacent-pipeline tiles belong to the same component. Per-component routing: each pipeline network's wells contribute crude to its refineries via the existing setpoint-priority `route_crude` logic. Orphaned wells (no pipeline neighbor) sell 100% of their crude raw at $40/bbl. Orphaned refineries (no pipeline neighbor, or pipeline-isolated from any well) starve at zero throughput. Pipelines stay at $2k CAPEX / $5/d OPEX; demolition is unguarded (no stranding check, since stranded wells still produce).

The full bundle moves the player from "drill anywhere, sell globally" to "explore narrowly, identify a reservoir, drill a producer at the core, place an injector at sweet spot inside the same reservoir, lay pipeline to a refinery, balance the rates." All five changes share the goal of making oilfield play **legible and decidable**.

## User Stories

### Player — exploration and survey

1. As a player, I want each survey to cost $15k at size 4, so my first exploration click feels familiar and affordable.
2. As a player, I want survey cost to scale as `(size/4)²`, so I can choose between many narrow surveys or fewer wide ones with a clear trade-off.
3. As a player, I want the default survey size in the build menu to be 4, so the cheapest option is the path of least friction.
4. As a player, I want the survey cost preview in the UI to update live as I change the size input, so I see the cost before I click.

### Player — reservoir identification

5. As a player, I want each HC voxel I survey to display its `reservoir_id`, so I know which voxels belong to the same geological body.
6. As a player, I want the cross-section view to color voxels by `reservoir_id`, so I can recognize a reservoir at a glance.
7. As a player, I want the `/reservoirs` view to group revealed voxels by reservoir, so I can see "reservoir R3 has 12 revealed voxels with total estimated 4.2M bbl."
8. As a player, I want surveying a column at the edge of a reservoir to give me enough information to infer the reservoir's `id`, so a follow-up small survey can extend my map without paying for a full column.

### Player — drilling decisions

9. As a player, I want the drill cost preview to reflect the depth-dependent CAPEX before I confirm, so I know exactly what a deep well will cost.
10. As a player, I want shallow reservoirs to be cheaper to drill than deep ones, so depth becomes a meaningful axis in well siting.
11. As a player, I want injection wells to follow the same depth-cost formula as production wells, so reservoir-pair planning stays symmetric.
12. As a player, I want a drill at z=0 to cost exactly the base CAPEX, so I can confirm the formula by reading the catalog.

### Player — well placement within reservoirs

13. As a player, I want to drill a producer and an injector in the same reservoir and see the producer's output rise as long as I run the injector, so reservoir management feels causal.
14. As a player, I want an injector placed inside the producer's 3×3×3 pool (chebyshev ≤ 1) to give *zero* pressure boost, so I learn the breakthrough penalty.
15. As a player, I want an injector in a different reservoir to give zero pressure boost even if pools overlap geometrically, so reservoir identity is the binding constraint.
16. As a player, I want to see in the well popup which reservoir my well is in and (for producers) which injectors are currently contributing pressure, so I can debug a producer that isn't getting boost.

### Player — rate management

17. As a player, I want production today to depend on yesterday's injection and production rates, so I can plan a balanced rate schedule.
18. As a player, I want stopping injection to drop the producer's pressure boost the next day, so an idle injector stops costing me power for nothing.
19. As a player, I want the well popup to show "yesterday inj rate" and "yesterday prod rate" so I can verify the pressure calculation.
20. As a player, I want pressure boost capped at 0.5 (the brief's value), so the cap is consistent with the rest of the spec.

### Player — pipelines and crude routing

21. As a player, I want crude from a production well to only reach a refinery if there's a connected pipeline path between them, so spatial planning matters.
22. As a player, I want a production well with no adjacent pipeline tile to sell all of its crude raw at $40/bbl, so the orphaned-well outcome is predictable.
23. As a player, I want a refinery with no pipeline connection to any well to receive zero crude, so the orphaned-refinery outcome is visible (and obviously wasteful).
24. As a player, I want two disjoint pipeline networks each with their own wells and refineries to route independently, so I can build separate oilfield clusters.
25. As a player, I want the map UI to render pipeline tiles distinctively, so I can trace network connectivity visually.
26. As a player, I want a yellow indicator on production wells that are selling raw because of no pipeline, and a red indicator on refineries with no crude, so orphans are obvious.
27. As a player, I want to demolish a pipeline tile freely without a "would_disconnect" gate, so I can rearrange networks without ceremony.

### Agent author

28. As an agent author, I want `/state.wells` to include `reservoir_id` for each well, so my agent can group wells by reservoir without computing connectivity itself.
29. As an agent author, I want `/state.reservoirs_revealed` voxels to include `reservoir_id`, so my agent can identify reservoir boundaries from survey data.
30. As an agent author, I want `/catalog.subsurface.drill` to expose the depth-cost formula (`base * (1 + (z/WORLD_D)**2)`), so my agent can compute drill cost for any candidate z.
31. As an agent author, I want `/catalog.subsurface.survey` to expose the new `(size/4)²` formula and new default size, so my agent picks survey sizes with correct costs.
32. As an agent author, I want each production well in `/state` to include `yesterday_prod_rate_bbl_day`, `yesterday_inj_rate_bbl_day` (summed over qualifying injectors), and `pressure_boost`, so my agent can audit pressure attribution.
33. As an agent author, I want the `/catalog.pipeline` entry to describe the connectivity rule, so my agent knows pipelines are load-bearing now.
34. As an agent author, I want a `/state.pipeline_networks` field that lists each connected network with the wells and refineries linked to it, so my agent can plan routing without recomputing graph adjacency from `/state.tiles`.

### Scripted baseline

35. As a maintainer, I want the scripted agent updated to survey at size 4, so its survey spend stays in line with the new pricing.
36. As a maintainer, I want the scripted agent updated to lay pipeline between every production well and its refinery, so the scripted baseline still produces and refines crude under the new rules.
37. As a maintainer, I want the scripted agent updated to drill injectors in the same reservoir as their producer, ≥2 voxels apart, so the rate-based pressure mechanic produces real boost in the baseline run.
38. As a maintainer, I want the scripted agent to set injection rates roughly equal to production rates, so the baseline keeps pressure healthy under the new ratio mechanic.
39. As a maintainer, I want `baselines/seed_42.json` regenerated from the updated scripted agent, so scoring reflects the new game.

### LLM agent

40. As a maintainer, I want the LLM agent's primer in `agents/prompts.py` updated with the new mechanics (reservoir identity, pressure-by-rate, depth costs, survey pricing, pipeline connectivity), so the model's policy is calibrated against the current rules.
41. As a maintainer, I want `agents/state_summary.py` to include the new fields (`reservoir_id`, `pipeline_networks`, `yesterday_*_rate`) in the compressed state, so the LLM has the information it needs.

### Determinism and tests

42. As a maintainer, I want the new BFS generator to consume the master seed's `sim_rng` deterministically (one random draw per blob center, radius, and percolation roll), so the determinism contract holds.
43. As a maintainer, I want `tests/test_determinism.py` to pass under the new generator, so byte-identical replay is preserved.
44. As a maintainer, I want existing tests that pin numerical outputs (production rates, refinery throughput) updated to match the new mechanics, so CI reflects the new contract.

## Implementation Decisions

### New module

- **`world/pipelines.py`** (new, deep module). Encapsulates:
  - `pipeline_components(tiles, w, h)` — returns a list of 4-connected pipeline components, each a `set[(x, y)]` of tile coordinates.
  - `routing_units(tiles, wells)` — returns a list of `(wells_in_network, refineries_in_network)` pairs plus an `orphan_wells` list. Sim iterates these to call `route_crude`.
  - Pure functions over `Tile`/`Well` lists, no `World` dependency. Testable without a sim instance.

### Modified modules

- **`world/subsurface.py`**:
  - `generate_subsurface` replaced with BFS percolation. Each blob seeds at a random center, then expands via a frontier queue. A candidate voxel is accepted with `p = HC_PROBABILITY_BASE * (1 - dist_to_center / r)` AND must be within Manhattan distance `r` AND must have ≥ 1 already-accepted neighbor in the 26-connected neighborhood. The seed voxel itself is always accepted. Each blob receives a unique `reservoir_id` (sequential integer starting at 1).
  - `Voxel` gains `reservoir_id: int` field.
  - New `voxel_reservoir_id(grid, x, y, z) -> int | None` helper.
  - New `well_reservoir_id(grid, x, y, target_z) -> int | None` helper — returns the `reservoir_id` of the target voxel if it is HC, else `None`.
  - `well_production_bbl_day` signature changes: replaces `inj_total_bbl: float` parameter with `qualifying_inj_rate_bbl_day: float` and `producer_yesterday_rate_bbl_day: float`. The pressure term becomes `min(0.5, qualifying_inj_rate / max(producer_yesterday_rate, 1.0))`.
  - `pools_intersect` retained only if other call sites need it; the production pressure path no longer uses it.
  - New `drill_capex(base_capex, target_z, world_d) -> float` helper exposing the depth quadratic.
  - Survey: change `survey_cost(size)` formula to `SEISMIC_BASE_COST * (size / 4) ** 2` and `SEISMIC_DEFAULT_SIZE` constant to `4`.

- **`world/state.py`**:
  - `Voxel`: add `reservoir_id: int` (default 0 for non-HC; 1+ for HC).
  - `Well`: add `reservoir_id: int | None` (resolved at drill time from target voxel).
  - `Well`: add `yesterday_rate_bbl_day: float` (set once per day at the start of the daily loop, before production/injection computation, from `current_rate_bbl_day`).

- **`world/sim.py`**:
  - At the start of `_advance_one_day`, snapshot each well's `current_rate_bbl_day` into `yesterday_rate_bbl_day`. Day 0 / day-of-drill: stays at 0.
  - Drill flow: compute drill cost via `drill_capex(...)`; deduct from treasury; resolve `well.reservoir_id` from target voxel; store on well.
  - Production loop: for each producer well, sum qualifying injectors' `yesterday_rate_bbl_day` (same `reservoir_id`, chebyshev > 1, both not None). Pass into `well_production_bbl_day` along with producer's own `yesterday_rate_bbl_day`. The `pools_intersect`-based aggregation is replaced.
  - Refinery routing: replace single `route_crude(refineries, total_crude_bbl)` with per-network routing. Use `pipelines.routing_units(...)` to enumerate `(wells_in_network, refineries_in_network)` pairs. For each, sum crude from those wells and call `route_crude`. Orphan wells: sum their crude, add to `crude_direct` (raw sale at $40/bbl) and skip routing.
  - `today_summary_so_far` keeps existing `crude_revenue`, `refined_revenue`, `oil_revenue` fields (no schema break).

- **`world/grid.py`**:
  - No changes. Pipeline connectivity lives in `world/pipelines.py`, not `grid.py`. The `road_connected_set` helper stays exactly as-is.

- **`world/catalog.py`**:
  - `pipeline` description updated to call out that connectivity is now load-bearing.
  - `build_catalog()` adds new fields under `subsurface.drill`: `cost_formula` describing the depth quadratic and `world_depth` so agents can compute it. `subsurface.survey` exposes the new `(size/4)²` formula and `default_size: 4`.

- **`world/economy.py`**:
  - `route_crude(refineries, total_crude_bbl)` signature **unchanged**. The per-network aggregation is the caller's responsibility (sim.py).
  - No change to `refine_one`, `refinery_process_kw`, or `daily_emissions_t`.

- **`world/api.py`**:
  - No endpoint shape changes (drill body still `{x, y, target_z, well_type}` — cost is server-computed).
  - `state_dict()` enriches each well with `reservoir_id`, `yesterday_rate_bbl_day`, and (for producers) `yesterday_inj_rate_bbl_day` + `pressure_boost`.
  - `state_dict()` adds top-level `pipeline_networks: list[{component_id, well_ids, refinery_ids}]` plus `orphan_well_ids` + `orphan_refinery_ids`.
  - `/reservoirs` voxel rows include `reservoir_id`.

- **`world/ui/app.js` + `index.html`**:
  - Survey size input defaults to 4 (`<input id="survey-size" ... value="4" />`).
  - Survey cost preview reads the new formula.
  - Drill cost preview computes per-z capex from the catalog formula.
  - Cross-section colors HC voxels by `reservoir_id` (palette: 8-color rotation, modulo collisions accepted on dense seeds).
  - Pipeline tiles rendered distinctively (pale blue or similar, no icon).
  - Well popup shows `reservoir_id`, `pressure_boost` (producers only), `yesterday_inj_rate` + `yesterday_prod_rate`.
  - Orphaned well badge: yellow "selling raw" indicator on producers with no pipeline neighbor.
  - Orphaned refinery badge: red "no crude" indicator on refineries that received 0 throughput yesterday because of pipeline isolation.

- **`agents/scripted.py`**:
  - Survey cadence kept, but `size = 4` (was 8).
  - After drilling a producer, lay pipeline tiles in a straight line (L-shaped path) to the nearest existing refinery; if no refinery exists yet, lay pipeline as part of the refinery-build flow.
  - Drill injector in same `reservoir_id` as producer, ≥2 voxels away (chebyshev). Set injector rate ≈ producer rate.
  - Wells reservoir lookup via `reservoir_id` exposed in `/state.wells`.

- **`agents/prompts.py`**, **`agents/state_summary.py`**:
  - Primer updated for new mechanics.
  - State summary includes `reservoir_id`, `pipeline_networks`, and per-well yesterday rates.

- **`baselines/seed_42.json`**:
  - Regenerated after `agents/scripted.py` is updated. Stale baseline is acceptable during development; CI tests that depend on baseline scoring will need the regen to pass.

### Architectural decisions

- **Single source of truth for reservoir identity**: the `reservoir_id` is assigned at generation and stored on every HC voxel. Wells resolve their `reservoir_id` at drill time from the target voxel. There is no runtime reconnection logic — if a voxel's oil is depleted, its `reservoir_id` is unchanged (the rock still belongs to that reservoir).
- **Lagged values via state snapshot, not separate read-models**: `yesterday_rate_bbl_day` is a real field on `Well`, updated once per day. No "compute on read" trickery.
- **Pipeline graph is read from `state.tiles` each day**: not cached. The graph is small (32×32 grid, few pipeline tiles in practice) and the computation runs once per day, not per hour. Keep it simple.
- **No transport cost on pipelines**: routing is binary connected-or-not. Capacity is a v2 feature explicitly out of scope here.
- **Cumulative injection bookkeeping retained as telemetry**: `cumulative_injected_bbl` stays on `Well` for the UI's "lifetime injected" stat, but is no longer used by the production formula.

### API contracts changed

- `/state.wells[*]` gains: `reservoir_id`, `yesterday_rate_bbl_day`. Producers also gain: `yesterday_inj_rate_bbl_day`, `pressure_boost`.
- `/state.reservoirs_revealed.top_k[*]` gains: `reservoir_id`.
- `/state` gains top-level: `pipeline_networks`, `orphan_well_ids`, `orphan_refinery_ids`.
- `/catalog.subsurface.drill.{production,injection}` gains: `cost_formula` (string), `world_depth` (int).
- `/catalog.subsurface.survey` gains: updated `cost_formula`, updated `default_size` (4).
- `/catalog.tiles[pipeline].description` updated.

No endpoint removed. No mutating-endpoint signature changes.

## Testing Decisions

A good test verifies **external behavior** through the simulator's public surface — `World.build()`, `World.drill()`, `World.step()`, `World.state_dict()`, `/catalog` — and asserts on the resulting state, not on intermediate variables or call patterns. Tests that pin specific numerical outputs (production rates, costs) are valuable because they catch silent formula regressions, but they must be tightened to the new constants.

### New test files

- **`world/tests/test_drill_cost.py`**:
  - z=0 cost equals base.
  - z=WORLD_D-1 cost equals `base * (1 + ((WORLD_D-1)/WORLD_D)²)`.
  - Symmetric formula applies to both `oil_well` and `injection_well` bases.
  - `/catalog` exposes the formula string and the world_depth constant.
  - Treasury debit at drill time matches `drill_capex(...)`.

- **`world/tests/test_pipelines.py`**:
  - Two pipeline tiles orthogonally adjacent form one network.
  - Two pipeline tiles diagonally adjacent form two networks.
  - A single network with one shipping well and one receiving refinery routes 100% of the well's crude through the refinery (subject to setpoint/capacity).
  - A well with no orthogonal pipeline neighbor sells 100% of its crude raw at $40/bbl regardless of refineries on the map.
  - A refinery with no orthogonal pipeline neighbor receives 0 throughput even if a well is producing.
  - Two disjoint networks each with their own well+refinery route independently (network A crude does not feed network B refinery).
  - Demolishing a pipeline tile that bridges two halves of a previously-connected network correctly recomputes routing the next day (orphans the now-isolated wells).

- **Extend `world/tests/test_subsurface.py`**:
  - Each blob is one connected component under 26-connectivity (`reservoir_id` is consistent across the blob).
  - `reservoir_id` is stable across reset+regenerate with the same seed.
  - HC voxels have `reservoir_id ≥ 1`; non-HC voxels are absent from `grid.voxels` (existing invariant).
  - Two blobs that spawn adjacent retain different `reservoir_id`s.
  - Total OOIP on seed 42 stays in the 5–15M bbl band the brief specifies (calibration regression).

- **Extend `world/tests/test_production.py` / `test_injection.py`**:
  - Drilling a producer with no injector → `pressure_boost` = 0 (yesterday_inj_rate = 0).
  - Drilling a producer + injector in same reservoir at chebyshev distance 2 → pressure_boost > 0 starting day 2 (day 1: yesterday rates are 0).
  - Same producer + injector at chebyshev distance 1 → pressure_boost = 0 (breakthrough).
  - Producer + injector in **different** reservoirs (drill at boundary) → pressure_boost = 0.
  - Idling an injector (setpoint = 0) for one day → pressure_boost drops to 0 the day after.
  - Two injectors qualifying for the same producer → their rates sum into the numerator.
  - Cap: very high injection rate vs low production rate → pressure_boost capped at 0.5.

- **Extend `world/tests/test_economy.py`**:
  - Crude routing through pipeline goes to the refinery on the same network only.
  - Orphan well crude appears in `today_summary_so_far.crude_revenue`, not in any refinery's throughput.
  - Pin updated to match new economics.

- **Extend `world/tests/test_determinism.py`**:
  - Two `reset(seed=42)` + identical action sequence produce byte-identical `state.tiles`, `state.wells`, `subsurface.voxels` (now with `reservoir_id`s), `treasury`, `population`.

### Prior art

Reference for testing patterns:
- `world/tests/test_subsurface.py` — already tests generator outputs against expected ranges.
- `world/tests/test_dispatch.py` — pure-function tests over `dispatch` without a full `World`.
- `world/tests/test_economy.py` — exercises `route_crude` directly.
- `world/tests/test_demolish_connectivity.py` — pattern for "graph mutation then re-query" tests; carry over for pipeline demolish tests.

`world/pipelines.py` is tested as a pure module (no `World` dependency) following the same shape as the existing `world/grid.py` road tests.

## Out of Scope

- **Pipeline transport cost or capacity limits**. v1 (and this PRD) keep pipelines binary. Throughput is unconstrained on a connected network; no $/bbl-km charge.
- **Pipeline routing through occupied tiles**. Pipelines can only be built on empty tiles, same as every other build. No "pipeline under road" stacking.
- **Reservoir-level pressure state**. We track rates, not a per-reservoir pressure scalar. The ratio is recomputed each day from yesterday's rates.
- **Smoothing or rolling-window rates**. Yesterday's rate (single day) is the input — no 7-day average.
- **Drill-through-rock variation by lithology**. The depth quadratic is the only depth-dependent cost. No "harder to drill through the third layer" mechanic.
- **Dynamic reservoir discovery**. `reservoir_id` is assigned at world generation. We do not re-label reservoirs as voxels deplete.
- **Multi-segment pipelines from one well to multiple refineries**. Routing is determined by network membership; we do not introduce a per-pipeline-tile flow allocation.
- **Updating the LLM agent's policy logic** beyond the prompt-primer and state-summary changes. Strategic improvements to the LLM agent are a separate concern.
- **Recalibrating starting cash**. If the new survey + drill costs make seed 42 infeasible for the scripted baseline, the response is to tune the scripted agent's behavior, not raise the $500k starting cash.
- **Pipeline "would_disconnect" gate**. Roads have one because civilian tiles instantly de-function; wells still produce when pipeline-stranded, so the gate isn't worth the code.

## Further Notes

- **Baseline regen is mandatory**. After landing this PRD, `baselines/seed_42.json` must be regenerated from a fresh scripted-agent run. CI tests that read the baseline (scoring tests) will fail until the regen lands. Bundle the regen with the final implementation issue, not as a follow-up.
- **Breaking change for existing tests**: tests that pin specific production rates, refinery revenue, or treasury deltas will fail. Updating them is part of the implementation work, not separate cleanup.
- **Order of implementation matters**: connected reservoirs (proposal 1) must land before rate-based pressure (proposal 2), because the latter consumes `reservoir_id`. Drill cost (3) and survey cost (4) are independent of each other and of 1+2. Pipelines (5) is independent but has the largest blast radius (touches the scripted agent and most economy tests).
- **Determinism contract**: every change must preserve byte-identical replay under the same seed and action log. The BFS generator changes the RNG draw sequence — but it stays deterministic, and the brief allows changing seeds → new layouts. The replay contract is between a fixed code version and a fixed seed; it does not require cross-version stability.
- **UI cross-section coloring by reservoir_id**: this is the single highest-leverage UX win in this PRD. A player who can see "this is reservoir R3, it spans 4 voxels" understands the placement rule instantly. Prioritize getting this right over the other UI changes.
- **`pools_intersect` and `cumulative_injected_bbl` cleanup**: both lose their primary call site. Leave `pools_intersect` in `subsurface.py` (no caller, but harmless); remove the `inj_total` aggregation in `sim.py`. Keep `cumulative_injected_bbl` on `Well` as telemetry but stop reading it for physics.
