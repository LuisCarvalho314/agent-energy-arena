# 07 — `world/pipelines.py` deep module (pure)

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

New pure module `world/pipelines.py` that encapsulates pipeline-graph reasoning over `Tile` / `Well` lists. No `World` dependency, no sim integration in this slice — that lands in issue 08. The module is testable in isolation, following the same shape as the road connectivity helpers in `world/grid.py`.

## Acceptance criteria

- [ ] `world/pipelines.py:pipeline_components(tiles, w, h) -> list[set[tuple[int, int]]]` returns 4-connected components of pipeline tiles (orthogonal adjacency only; diagonals are separate components).
- [ ] `world/pipelines.py:routing_units(tiles, wells) -> tuple[list[tuple[list[Well], list[Tile]]], list[Well], list[Tile]]` returns `(networks, orphan_wells, orphan_refineries)` where each network is `(wells_in_network, refineries_in_network)`. A well belongs to network N if it has an orthogonal pipeline neighbor in N; same for refineries. Wells/refineries with no orthogonal pipeline neighbor are orphans.
- [ ] Pure functions — no mutation of inputs, no `World` import.
- [ ] New `world/tests/test_pipelines.py`:
  - [ ] Two pipeline tiles orthogonally adjacent → one component.
  - [ ] Two pipeline tiles diagonally adjacent only → two components.
  - [ ] One network with one shipping well and one receiving refinery → `routing_units` returns one `(wells, refs)` pair containing both, empty orphan lists.
  - [ ] Well with no orthogonal pipeline neighbor → appears in `orphan_wells`, not in any network's `wells`.
  - [ ] Refinery with no orthogonal pipeline neighbor → appears in `orphan_refineries`.
  - [ ] Two disjoint networks each with their own well + refinery → two `(wells, refs)` pairs, each containing only its own well + refinery.
  - [ ] Removing a bridging pipeline tile splits a previously-connected network into two on the next call.
- [ ] `make check` passes.

## Blocked by

None - can start immediately.
