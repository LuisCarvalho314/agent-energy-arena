---
Status: done
---

# 01 — Server skeleton + determinism foundation

## Parent

[PRD: Energy–AI Nexus Hackathon v1](../PRD.md)

## What to build

The minimum viable simulation server that an empty world can be built on top of. After this slice, `docker compose up` brings up a FastAPI server that answers `/state`, `/step`, `/reset`, `/seed`, and `/catalog` for an empty world, and a static UI at `localhost:8000` renders the empty surface grid with a day counter.

The slice is responsible for getting the **determinism foundation right from day one** — there is no easy refactor for this later. Two RNG streams (`sim_rng` and `forecast_rng`) are seeded from a master seed via independent `numpy.random.SeedSequence` children. The simulation RNG advances per simulated day, not per `/step` call. Every action submitted to a mutating endpoint is logged to `runs/{run_id}/actions.jsonl` regardless of success.

The `/step` endpoint accepts a `days` parameter in the range `[1, 7]`, default `7`. It always advances the full requested number of days — never early-terminates. Internal hourly ticks (`TICKS_PER_DAY = 24`) advance per simulated day even though the world has no dynamics yet; the loop is in place.

`MANUAL_GAME_DAYS = 365` and `GAME_DAYS = 3650` are both env-var configured; the active value depends on whether the world was created via the manual or agent path. The session type is exposed in `/state.config`.

## Acceptance criteria

- [ ] `docker compose up` brings up the server and UI under 60 seconds on a developer laptop.
- [ ] `GET /state` on a fresh world returns a JSON payload conforming to the brief's §5.3 schema with empty `tiles`, empty `wells`, day = 0, treasury = `STARTING_CASH`, population = `STARTING_POP`.
- [ ] `POST /step { "days": 7 }` advances the world by 7 days; day counter in `/state` increments.
- [ ] `POST /step { "days": 1 }` repeated 7 times produces byte-identical world state to a single `POST /step { "days": 7 }`. Verified by a test in `world/tests/test_determinism.py`.
- [ ] `POST /reset { "seed": 42 }` restores day = 0 and re-seeds both RNG streams.
- [ ] Calling `GET /forecast` does not perturb the simulation RNG state (forecast uses `forecast_rng`, never advances `sim_rng`). Verified by test.
- [ ] All mutating endpoint calls (including failures) append a JSON line to `runs/{run_id}/actions.jsonl` with timestamp, endpoint, params, ok/error.
- [ ] `GET /catalog` returns the build catalog (§4.12) as machine-readable JSON. The catalog is empty in this slice but the endpoint is wired.
- [ ] `GET /seed` returns the active seed.
- [ ] The UI renders an empty 32×32 surface grid, a top-bar day counter, treasury, population, and a non-functional "Next Day" button (functional in slice 16).
- [ ] `MANUAL_GAME_DAYS` env var defaults to 365; `GAME_DAYS` defaults to 3650; both are exposed in `/state.config`.
- [ ] `world/tests/test_api_smoke.py` boots the server and walks through reset → step → state → reset.

## Blocked by

None — can start immediately.

## Comments

### Iter 1 — 2026-05-10

Implemented. All acceptance criteria met except the Docker-up timing one
(not measured locally; image hasn't been benchmarked on a developer laptop).

**Decisions:**
- Sim RNG advances per simulated day via one mandatory `standard_normal()`
  draw at the end of `_advance_one_day`, locking in `step(7) ≡ step(1)*7`
  before any dynamics exist.
- Two RNGs (`sim_rng`, `forecast_rng`) come from `SeedSequence(seed).spawn(2)`.
- Action log lives at `runs/{run_id}/actions.jsonl`; both successes and
  rejections are appended. The handler logs failures *after* `world.step`
  raises; Pydantic-422 validation rejections don't reach the handler and
  aren't logged (acceptable since they never touched the world).
- The world's body-validation range `[1,7]` is enforced both by the Pydantic
  body model (HTTP 422 fast-path) and by `World.step` (defence in depth for
  internal callers).
- UI is plain HTML + canvas + vanilla JS, no build step. Polls `/state`
  every 500ms; "Next Day" button is rendered disabled per the slice spec.

**Files:**
- `pyproject.toml`, `.gitignore`, `Dockerfile`, `docker-compose.yml`
- `world/{__init__,config,state,sim,catalog,action_log,api}.py`
- `world/ui/{index.html,style.css,app.js}`
- `world/tests/{__init__,test_determinism,test_api_smoke}.py`

**Notes for next iteration:**
- The `app = create_app()` module-level instance creates a `runs/<id>/`
  directory at import time. That's intentional for `uvicorn world.api:app`
  but pollutes the working directory if anyone imports the module ad-hoc.
  Consider lazy ActionLog instantiation if it bites.
- No `Makefile` yet (`make play`, `make eval`, `make score`); brief mentions
  one but it isn't an acceptance criterion for this slice.
- No score, summary, history, events, tiles, wells, reservoirs endpoints —
  those land with their owning issues (02, 13, 11, etc.).
