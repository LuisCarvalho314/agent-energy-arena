# 05 — Quadratic-in-depth drilling cost

Status: needs-triage

## Parent

`.scratch/oilfield-v2/PRD.md`

## What to build

Drilling cost scales with target depth: `capex(z) = base * (1 + (target_z / WORLD_D)**2)`, applied to both production and injection wells with their own bases. Catalog exposes the formula so agents can compute it; UI cost preview reads target_z.

## Acceptance criteria

- [ ] New `drill_capex(base_capex, target_z, world_d) -> float` helper in `world/subsurface.py`.
- [ ] `world/sim.py` drill flow computes capex via `drill_capex(...)` and debits treasury by that amount (was flat base).
- [ ] `Well.capex_paid` reflects the depth-scaled value (snapshot-on-build pattern preserved).
- [ ] `/catalog.subsurface.drill.production` and `.injection` each add `cost_formula: "base * (1 + (target_z / world_depth)**2)"` and `world_depth: <WORLD_D>`. `base_capex` already present stays unchanged.
- [ ] UI drill cost preview computes per-z capex from the catalog formula and updates as the player picks a target voxel.
- [ ] New `world/tests/test_drill_cost.py`:
  - [ ] `z = 0` returns the base.
  - [ ] `z = WORLD_D - 1` returns `base * (1 + ((WORLD_D-1)/WORLD_D)**2)`.
  - [ ] Formula applies to both `oil_well` and `injection_well` bases.
  - [ ] Treasury debit on `/drill` matches `drill_capex(...)` for a known target_z.
  - [ ] `/catalog` exposes `cost_formula` and `world_depth` strings/ints.
- [ ] `make check` passes (existing tests that pinned a flat $50k / $30k drill cost must be updated).

## Blocked by

None - can start immediately.
