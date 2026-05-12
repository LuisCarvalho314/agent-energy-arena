# 01 — BFS reservoirs + `reservoir_id` end-to-end (backend)

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Replace the per-cell stochastic HC generator in `world/subsurface.py` with a BFS percolation generator so every reservoir is connected-by-construction. Tag each HC voxel with a `reservoir_id` (sequential integer starting at 1 per blob). Wells resolve and store the `reservoir_id` of their target voxel at drill time. `/reservoirs` and `/state.wells` expose the new field. No UI work in this slice (the cross-section coloring lives in issue 02).

## Acceptance criteria

- [ ] `world/subsurface.py:generate_subsurface` rewritten as BFS percolation: each blob picks a seed voxel (always accepted), then expands via a frontier queue. A candidate voxel is accepted iff (a) within Manhattan distance `r` of the seed, (b) passes `p = HC_PROBABILITY_BASE * (1 - dist/r)`, and (c) has ≥ 1 already-accepted neighbor in its 3×3×3 (26-connected) neighborhood.
- [ ] `Voxel` gains `reservoir_id: int` (HC voxels: ≥ 1; non-HC voxels are absent from `grid.voxels`, unchanged invariant).
- [ ] Two blobs that spawn adjacent retain distinct `reservoir_id`s (no merging across the seam).
- [ ] `Well` gains `reservoir_id: int | None`, resolved at drill time via a new `well_reservoir_id(grid, x, y, target_z)` helper. Drilling rock (non-HC voxel) leaves it `None`.
- [ ] `state_dict()` includes `reservoir_id` on every well; `/reservoirs` voxel rows include `reservoir_id`.
- [ ] `world/tests/test_subsurface.py` extended:
  - [ ] Each blob is a single connected component under 26-connectivity.
  - [ ] `reservoir_id` is stable across `reset(seed=42)` repeats.
  - [ ] Adjacent-spawn blobs retain different `reservoir_id`s on a constructed seed.
  - [ ] Seed-42 OOIP stays in the 5–15M bbl band (calibration regression).
- [ ] `world/tests/test_determinism.py` still passes (RNG draw sequence changes are allowed; cross-seed replay must remain byte-identical within the new code).
- [ ] `make check` passes.

## Blocked by

None - can start immediately.
