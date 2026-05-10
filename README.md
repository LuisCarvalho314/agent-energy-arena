# Energy–AI Nexus

A small, deterministic Python simulation of a city's energy economy for the **EAGE Annual 2026 Energy–AI Nexus Hackathon**. A FastAPI server is the single source of truth; a browser UI and AI agents play against the same HTTP API.

> **Status:** in active development. Slices 01 (server skeleton + determinism) and 02 (surface tiles, treasury, town hall, adjacency) have landed. Subsequent slices — population, weather/demand, dispatch, subsurface, wells, refinery, events, scoring, reference agents — are tracked under `.scratch/energy-ai-nexus/issues/`.

## What this is

Players site renewable and fossil power generation, civilian buildings, and oil/gas infrastructure on a 32×32 surface. They explore a 16-deep voxel subsurface via seismic surveys, drill production and injection wells, refine and sell crude, and grow population — all while keeping the grid balanced hour-by-hour without battery storage.

The full design is in **[docs/hackathon-brief.md](docs/hackathon-brief.md)** (binding spec — equations, API contracts, build catalog). Implementation decisions and overrides live in the **[PRD](.scratch/energy-ai-nexus/PRD.md)**.

## Quickstart

The three commands every participant must remember (brief §11.2):

```sh
make play     # docker compose up — manual play at http://localhost:8000
make eval     # docker compose --profile eval run agent — score submit/agent.py
make score    # run the scripted agent on seed 42, print the score JSON
```

`make play` brings up the world API + UI on `http://localhost:8000`; `runs/` is mounted so action logs persist across container restarts. `make eval` mounts `./submit/` read-only into the `agent` container and invokes `python evaluate.py --agent submit.agent --seed 42` against the running world.

Participants edit two files:

- **`submit/agent.py`** — your `Agent` class. The default re-exports `agents.scripted.ScriptedAgent` so a clean clone matches the committed baseline.
- **`submit/WRITEUP.md`** — 1-page approach summary submitted alongside the agent.

### Local (Python 3.11+)

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
make serve
```

`make serve` runs uvicorn locally without docker; UI at http://localhost:8000, API docs at http://localhost:8000/docs.

### Replay

Every game writes `runs/{run_id}/actions.jsonl` plus `final_state.json`. Re-run a game from its log:

```sh
python evaluate.py --replay runs/{run_id}
```

Exit 0 if the replayed final state is byte-identical to the recorded one; exit 1 on drift. Determinism is per `(seed, action_log)`.

### Tests

```sh
pytest world/tests
```

Determinism, API smoke, grid/build, and slice-level coverage. Add `-v` for per-test names.

## Repository layout

```
world/
  api.py            # FastAPI endpoints
  sim.py            # tick loop, orchestrator
  state.py          # core dataclasses
  grid.py           # surface tile placement, adjacency, demolition
  catalog.py        # build-catalog (CAPEX/OPEX) as machine-readable JSON
  config.py         # all env-var tunables — single point of definition
  action_log.py     # append-only JSONL log of every mutation
  ui/               # static HTML + Canvas + vanilla JS for manual play
  tests/            # pytest suite
docs/
  hackathon-brief.md  # binding design spec
  agents/             # internal docs for issue tracker, triage, domain
.scratch/
  energy-ai-nexus/    # PRD + issue tracker for ongoing work
runs/                 # per-run action logs (mounted into the container)
```

Target line counts when complete: `world/` ~1800 LoC, `world/ui/` ~600, `agents/` ~800, `tests/` ~600. The whole world codebase is meant to be readable end-to-end in 30–45 minutes.

## API surface (currently wired)

| Method | Path | Notes |
|---|---|---|
| `GET`  | `/state`     | Full world state |
| `GET`  | `/seed`      | Active seed |
| `GET`  | `/catalog`   | Build catalog |
| `GET`  | `/forecast`  | 24h weather/demand forecast (stub until §4.9 lands) |
| `POST` | `/reset`     | `{ "seed": int? }` |
| `POST` | `/step`      | `{ "days": 1..7 }` (default 7) |
| `POST` | `/build`     | `{ "tile_type", "x", "y" }` |
| `POST` | `/demolish`  | `{ "x", "y" }` |

Mutating endpoints return `{ ok, error?, treasury_after, result }`. Errors are human-readable strings (`insufficient_funds`, `no_road_adjacency`, `tile_occupied`, `cannot_demolish_townhall`). Every attempt — success or rejection — is appended to `runs/{run_id}/actions.jsonl`.

The full sixteen-endpoint contract (surveys, drilling, wells, refinery control, scoring, history, events) is specified in [the brief §5.2](docs/hackathon-brief.md) and lands incrementally.

## Configuration

All tunables live in `world/config.py` and read environment variables at startup. Notable defaults:

| Var | Default | Notes |
|---|---|---|
| `WORLD_SEED` | 42 | dev seed |
| `WORLD_W` / `WORLD_H` / `WORLD_D` | 32 / 32 / 16 | surface and subsurface dims |
| `GAME_DAYS` | 3650 | 10-year agent game (PRD override of brief's 365) |
| `MANUAL_GAME_DAYS` | 365 | one-year human tutorial session |
| `TICKS_PER_DAY` | 24 | hourly internal cadence |
| `STARTING_CASH` | 500000 | |
| `STARTING_POP` | 100 | |
| `API_PORT` | 8000 | |

See the brief §9 and PRD for the full list including economics, carbon price, and event-related tunables.

## Determinism

The simulation is fully deterministic given `(seed, action_log)`. Two RNG streams branch from the master seed via `numpy.random.SeedSequence`:

- `sim_rng` — world dynamics (weather noise, event rolls, reservoir generation). Advances per simulated day, so `step(days=7)` is byte-identical to seven `step(days=1)` calls.
- `forecast_rng` — forecast noise per `/forecast` call. Independent of `sim_rng` so calling the forecast doesn't perturb simulation state.

`tests/test_determinism.py` enforces these invariants.

## Contributing

This repo follows a small set of agent conventions documented in [`docs/agents/`](docs/agents/):

- **Issue tracker** — issues are markdown files under `.scratch/<feature>/`. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- **Triage labels** — canonical five-role vocabulary. See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).
- **Domain docs** — `CONTEXT.md` + `docs/adr/` at the repo root. See [`docs/agents/domain.md`](docs/agents/domain.md).

When working on a slice, every formula in §4 of the brief must appear as a named function in the corresponding module with the same variable names — this is a hard design rule, not coincidence.
