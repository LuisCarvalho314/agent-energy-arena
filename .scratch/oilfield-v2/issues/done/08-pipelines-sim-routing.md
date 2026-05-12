# 08 — Pipelines: sim routing + orphan rules

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Wire `world/pipelines.py` into the daily sim so crude only flows from producers to refineries on the same 4-connected pipeline network. Orphaned producers (no pipeline neighbor) sell 100% of their crude raw at $40/bbl; orphaned refineries (no pipeline neighbor or pipeline-isolated from any well) starve at zero throughput. `route_crude` itself is unchanged — the caller drives per-network aggregation. `/state` exposes the network graph so agents don't have to recompute it.

## Acceptance criteria

- [ ] `world/sim.py` refinery-routing block calls `pipelines.routing_units(state.tiles, state.wells)` once per day.
- [ ] For each `(wells_in_network, refineries_in_network)` pair: sum that network's crude from its producers, call existing `route_crude(refineries_in_network, network_crude)`, and apply per-refinery actuals as today.
- [ ] Orphan producers contribute their crude to `today_summary_so_far.crude_revenue` (raw sale at $40/bbl) and skip routing entirely.
- [ ] Orphan refineries get `current_throughput_bbl_day = 0` and `current_refined_bbl_day = 0` — pinned uniformly like the existing zero-crude case.
- [ ] `/state` adds top-level `pipeline_networks: list[{component_id, well_ids, refinery_ids}]`, `orphan_well_ids: list[str]`, `orphan_refinery_ids: list[str]`.
- [ ] `world/tests/test_economy.py` extended:
  - [ ] Producer + refinery on the same network → refinery receives the producer's crude (subject to setpoint/cap).
  - [ ] Producer with no pipeline neighbor → its crude shows in `crude_revenue` at $40/bbl, refinery throughput is 0.
  - [ ] Refinery with no pipeline neighbor + producer on another network → refinery throughput is 0, producer's crude routes only within its own network.
  - [ ] Two disjoint networks each with their own well+refinery → network A crude does not reach network B refinery.
  - [ ] Demolishing a bridging pipeline tile correctly orphans the now-isolated wells on the next day.
- [ ] `make check` passes. Tests that pinned global-routing throughput/revenue are updated.

## Blocked by

- `.scratch/oilfield-v2/issues/07-pipelines-module.md`
