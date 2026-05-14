# `/step` is not an Action

The [[executor]] consolidates all mutating endpoints (`/build`, `/demolish`, `/survey`, `/drill`, `/control/*`, `/reset`, `/scenario`) behind one gate; `/step` is deliberately left outside.

## Decision

`/step` is not an [[Action]] and does not flow through `executor.execute`. Its endpoint handler writes its own `action_log` entry directly; replay's `_dispatch` special-cases `step` as a single bypass before invoking the executor for the rest.

## Rationale

- **Result shape mismatch.** `/step` returns `{day_completed, summary, treasury_after, ok}` with a nested `summary` payload that doesn't fit `ActionResult`'s `{ok, error?, treasury_after, result?}` envelope. Coercing it would either force a sum type on `ActionResult` (defeating the unified envelope that justifies the executor) or squash `summary` into `result`, losing typing.
- **Step's mutation is a separate deepening seam.** The 1186-line day-loop in `world/sim.py` is candidate #1 in the architecture review the executor is candidate #3 of. Routing `step` through the executor would smuggle that refactor into this one and tangle the two seams.
- **Trivial validation.** `/step` has no `(validate → mutate)` shape worth gating: a single `1 ≤ days ≤ 7` check. The cross-cutting concerns the executor exists to consolidate (validation routing, log writing, replay reconstruction, error envelope normalisation) don't apply.

## Consequences

- `Action.from_log_entry` raises `UnknownActionError` on `/step` entries. Replay handles this by routing to `api.step(...)` before calling the executor.
- The day-loop refactor (candidate #1) can name its own seam when it lands without being forced to live behind `executor.execute`.

## Rejected alternative

Make `Action` a sum that includes a `Step` variant with a `StepResult` companion on the result side. Rejected: forces a sum on `ActionResult`, defeating the unified envelope; couples this PR to the day-loop refactor.
