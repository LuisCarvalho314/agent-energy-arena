---
Status: needs-triage
---

# Volume rescale: VOXEL_VOLUME_BBL 700k → 70k

## Parent

`.scratch/reservoir-scale-and-stacked-completions/PRD.md`

## What to build

Drop `VOXEL_VOLUME_BBL` from `700_000` to `70_000` (10×) so a 10-year game horizon produces legible reservoir depletion. The per-voxel OIP formula (`porosity × s_o × VOXEL_VOLUME_BBL`) reads through transparently; no other physics constants change (`Q_MAX_WELL_BBL_DAY` stays at 200, `PRESSURE_BOOST_MAX` stays at 0.5). Existing slice-01 reservoir-summary tests continue to pass with values shifted 10× downward. The seed-42 baseline drifts in a documented direction (lower per-voxel OIP → lower revenue per producer-day); update `baselines/seed_42.json` `p_ref` / `t_ref` to the new deterministic values.

## Acceptance criteria

- [ ] `VOXEL_VOLUME_BBL = 70_000` in `world/subsurface.py` (or wherever the constant lives today)
- [ ] No other physics constants touched in this slice
- [ ] All existing tests pass under the new constant (numeric assertions in slice-01 tests updated to 1/10 expected values)
- [ ] `baselines/seed_42.json` regenerated; the determinism smoke test gates on the new `p_ref`/`t_ref` with the existing 5% slack
- [ ] Commit message documents the directional drift (revenue per producer-day down ~10×)
- [ ] `make check` is green

## Blocked by

None - can start immediately
