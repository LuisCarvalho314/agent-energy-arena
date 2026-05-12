---
Status: needs-triage
---

# `supports_producer_ids` on injection wells

## Parent

`.scratch/wells-reservoir-rollup/PRD.md`

## What to build

A new field on the per-well dict returned by `world/sim.py:_well_to_dict()`: `supports_producer_ids`. For injection wells, the field is the sorted list of production-well ids that share the injector's `reservoir_id` AND whose `(x, y, target_z)` sit at 3D Chebyshev distance strictly greater than 1 from the injector's `(x, y, target_z)`. For production wells, the field is an empty list (the field is present for type symmetry; the UI ignores it on producer rows).

The qualification rule already exists in `world/sim.py:794-820` (used to compute each producer's `pressure_boost`). This issue lifts the same gate into a pure helper in `world/subsurface.py` named `injector_supports(injector, wells) -> list[str]`, so the rule has a single source of truth and is unit-testable in isolation. `_well_to_dict()` calls the helper for injectors and adds the result to the dict.

The field flows automatically into the `/state.wells[*]` array and into the `/drill` response (which already wraps `_well_to_dict(well)`).

## Acceptance criteria

- [ ] New pure helper `injector_supports(injector, wells) -> list[str]` in `world/subsurface.py`. Takes a single injection `Well` and an iterable of all `Well`s; returns the ascending-sorted list of producer ids.
- [ ] Producers in a different reservoir than the injector are excluded from the result.
- [ ] Producers at 3D Chebyshev distance ≤ 1 from the injector's `(x, y, target_z)` are excluded (adjacency / breakthrough gate).
- [ ] Producers at 3D Chebyshev distance ≥ 2 in the same reservoir are included.
- [ ] Result is sorted by ascending producer-id string.
- [ ] Injectors whose `reservoir_id` is `None` (drilled into rock) return `[]`.
- [ ] `world/sim.py:_well_to_dict()` calls the helper for injection wells and adds `supports_producer_ids` to the returned dict. For production wells, the field is set to `[]`.
- [ ] The qualification logic in `world/sim.py:794-820` (boost computation) is refactored to call the same helper, so there is exactly one place that owns the same-reservoir + Chebyshev > 1 rule. Boost values must not change as a result of the refactor.
- [ ] New unit tests in `world/tests/test_subsurface.py` cover: cross-reservoir exclusion, Chebyshev-1 exclusion, Chebyshev-2 inclusion, multi-producer ascending sort, null-reservoir injector returns `[]`.
- [ ] `/state` smoke assertion in `world/tests/test_api_smoke.py`: after drilling at least one injection well, `state.wells[i]["supports_producer_ids"]` is present and is a list.
- [ ] `/drill` response includes `supports_producer_ids` on the returned well dict (covered by existing `_well_to_dict` flow; assertion in `test_api_smoke.py` or `test_drill_cost.py`).
- [ ] Existing pressure-boost regression tests (in `world/tests/test_injection.py`, `world/tests/test_production.py`) continue to pass with no expected-value changes.
- [ ] `make check` passes (ruff, format, mypy, pytest).

## Blocked by

None — can start immediately, in parallel with #01.
