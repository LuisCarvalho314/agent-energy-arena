Status: needs-triage

## Parent

PRD: `.scratch/balance-upgrade-p0/PRD.md`

## What to build

Refresh the checked-in baseline and add a determinism replay assertion so downstream scoring compares against a coherent post-upgrade reference. Without this, R_ref stays at the legacy ~0.04 and the scoring ratio in the upgraded R term becomes meaningless.

- Regenerate `baselines/seed_42.json` by running the updated scripted agent (with battery build rule from #2) to completion on seed 42. This is the only baseline file checked in; organizers regenerate the eval-seed baseline at scoring time.
- Add a fresh seed-42 replay assertion in `test_determinism.py`. Keep existing replay tests intact; do not parameterize for a flag (there is no flag).

## Acceptance criteria

- [ ] `baselines/seed_42.json` regenerated and committed.
- [ ] Baseline reflects a battery-using scripted agent (R-term moves from ~0.04 toward the targeted ~0.06–0.08).
- [ ] New seed-42 replay test passes byte-identically across runs.
- [ ] Existing determinism tests still pass.
- [ ] `make check` passes.

## Blocked by

- `02-battery-dispatch-and-scripted-agent.md`
- `03-coal-rebalance-and-fuel-shock.md`
- `04-happiness-depth.md`
- `05-heatwave-solar-derate.md`
