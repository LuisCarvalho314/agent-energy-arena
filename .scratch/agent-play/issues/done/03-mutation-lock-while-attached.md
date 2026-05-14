---
Status: ready-for-agent
---

# Mutation lock while attached

## Parent

[PRD: Agent Play](../PRD.md)

## What to build

While an agent is attached, the human owns the clock; the agent owns world mutations. Disable every world-mutation control in the UI for the duration of the attach so the human cannot contest the agent mid-turn. Keep clock controls (Play / Fast / Next Day / Prev Day) and the map / panels / replay-backward fully usable.

Introduce `isMutationLocked()` returning `isReplay() || isAgentAttached()`. Replace `isReplay()` at the ~9 mutation-guard handler sites and the well/refinery/battery slider `disabled` flags. Leave replay-UI-rendering sites on `isReplay()` alone — the helper's name is load-bearing: it tells the next reader the invariant is "world mutation is locked", not "we are in replay".

Scenario controls (attach/detach scenario, scenario-replay seek, etc.) are also gated by `isMutationLocked()` so the human cannot swap the scenario out from under the agent.

## Acceptance criteria

- [ ] `isAgentAttached()` and `isMutationLocked()` defined in `world/ui/app.js`.
- [ ] `isReplay()` calls at mutation-guard sites are replaced with `isMutationLocked()`. Replay-UI-rendering sites are unchanged.
- [ ] While attached: Build, Demolish, Survey, Drill controls are disabled.
- [ ] While attached: well, refinery, and battery rate sliders are disabled.
- [ ] While attached: scenario attach/detach and related scenario controls are disabled.
- [ ] While attached: Play, Fast, Next Day, Prev Day remain enabled.
- [ ] On Detach, all mutation controls re-enable.
- [ ] Manual smoke: attach a no-op `BaseAgent` and confirm the disabled-state matrix in the browser.
- [ ] `make check` passes.

## Blocked by

- #01 — Attach/detach + per-turn callback (tracer bullet)
