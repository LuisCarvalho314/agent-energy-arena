---
Status: ready-for-agent
---

# `act()` crash safety + clock-violation guard

## Parent

[PRD: Agent Play](../PRD.md)

## What to build

Make Agent Play robust to two failure modes that will absolutely happen during agent development:

1. **`act()` raises mid-turn.** The day must not advance, the agent must stay attached, and the developer must see the exception message in the UI without grepping server logs.
2. **Agent accidentally calls a clock method.** Calls to `api.step()`, `api.reset()`, or `api.attach_scenario()` from inside `act()` must raise client-side (before the FastAPI TestClient call), so the action log never sees the rejected request and the "human owns the clock" invariant is enforced at the boundary.

Scope:

- **`agents/api_client.py`**: `UiAgentApiClient.step`, `.reset`, `.attach_scenario` each raise `RuntimeError` with a message naming the violation (e.g. `"in Agent Play, the human drives /step"`). Raises are client-side, *before* the TestClient call.
- **`world/api.py`**: when an attached agent's `act()` raises, return 500 with `detail = f"agent.act raised: {exc!r}"`, skip `world.step`, leave `app.state.attached_agent` and `app.state.attached_agent_folder` intact.
- **`world/ui/app.js`**: the existing `/step` error path (`pauseTimer()` + `showToast()`) already handles 5xx — verify it surfaces the server's detail message and does not detach.

## Acceptance criteria

- [ ] `UiAgentApiClient.step` raises `RuntimeError` client-side; nothing reaches the TestClient; no row is appended to `actions.jsonl`.
- [ ] Same for `UiAgentApiClient.reset` and `UiAgentApiClient.attach_scenario`.
- [ ] When an attached agent's `act()` raises, `POST /step` returns 500 with `detail` containing `"agent.act raised:"` and the exception's `repr`.
- [ ] After `act()` raises, the world's day counter is unchanged.
- [ ] After `act()` raises, `GET /agent` still reports the attached folder.
- [ ] When an attached agent's `act()` calls `self.api.step(days=1)`, `POST /step` returns 500, the day did not advance, and the agent stays attached. (One test covers `api.step`; the `UiAgentApiClient` shape means `api.reset` and `api.attach_scenario` ride along.)
- [ ] World UI: a 500 from `POST /step` pauses the timer and shows a toast containing the server's detail. Manual smoke with a stub that raises confirms.
- [ ] Tests added to `world/tests/test_agent_attach.py`.
- [ ] `make check` passes.

## Blocked by

- #01 — Attach/detach + per-turn callback (tracer bullet)
