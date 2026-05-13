# Agent Energy Arena

A small, readable Python simulation of a city's energy economy, wrapped by a FastAPI server, used as a benchmark for autonomous agents. Site renewables, fossil plants, batteries, oil wells, and refineries. Keep the grid balanced hour-by-hour and grow population over a multi-year game. Submit an agent, compare it against the community on shared stress scenarios.

The world is the single source of truth. Two clients consume the same API: a browser UI for manual play, and AI agents that play autonomously.

## What you came here to do

| You want to… | Read |
|---|---|
| Understand the game so you can build an agent | [RULES.md](RULES.md) |
| Look up an endpoint or response shape | [API.md](API.md) |
| Write a stress scenario | [SCENARIOS.md](SCENARIOS.md) |
| Submit an agent | [CONTRIBUTING.md](CONTRIBUTING.md) |
| See how the community ranks | [LEADERBOARD.md](LEADERBOARD.md) |

## 60-second tour

The simulator runs in ticks (1 hour) and days (24 ticks). Agents call `POST /step` once per game day after submitting actions for that day. A game is `GAME_DAYS` days (default 3650 = 10 years for evaluation, 365 for manual play).

Each day the world:

1. Expires finite-duration events.
2. Runs the attached scenario's `apply(world, day)` hook (default: no-op).
3. Samples stochastic events (heatwave, fuel shock, plant failure, demand surprise, regulatory tightening).
4. Steps 24 hours: weather, dispatch, grid balance, population, finance.
5. Emits a daily summary; records the end-of-day state.

The score is `0.5·population + 0.4·tanh(treasury delta) + 0.1·renewable share`, with population and treasury normalised against a reference scripted-agent run on the same seed. The exact formula and reference policy live in [RULES.md §Scoring](RULES.md#scoring).

## Quickstart

```bash
make install                              # one-time: pip install -e ".[dev]"
make serve                                # uvicorn on :8000 — open the UI in a browser
make score                                # run the scripted reference agent on seed 42
make check                                # lint + format-check + typecheck + test
```

Docker is also supported:

```bash
docker compose up                                   # manual play at :8000
docker compose --profile eval run --rm agent       # evaluate submit/agent.py
```

## Submit an agent

1. Fork the repo.
2. Drop your agent under `agents/community/<your_handle>.py` as a single Python file with a class that satisfies the `Agent` protocol (see [agents/base.py](agents/base.py)).
3. Open a PR. CI runs `make check`. A maintainer regenerates `LEADERBOARD.md` on merge.

Full submission protocol: [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

```
world/              # the simulation, API, and UI (single source of truth)
agents/             # reference agents + community submissions
  base.py             Agent protocol + BaseAgent helper
  scripted.py         rule-based reference (forms baselines/seed_42.json)
  llm_react.py        OpenAI-compatible LLM ReAct agent
  langgraph_agent.py  LangGraph variant
  community/          one .py per community submission (created on first PR)
scenarios/          # one Python file per shipped stress scenario
  baseline.py         null scenario on seed 42
  grid_stress.py      sustained low-wind + heatwave cluster
  economy_stress.py   fuel shock + crude collapse + regulatory tightening
arena/              # multi-(agent, scenario) runner + leaderboard
  runner.py           subprocess-isolated runner; `python -m arena.runner`
  leaderboard.py      mean-rank aggregator → Markdown table
  baselines.py        regenerates baselines/arena/<scenario>-<seed>.json
baselines/          # committed reference scores
docs/               # internal agent-skill docs + archived design briefs
runs/               # gitignored; one folder per recorded game session
evaluate.py         # CLI: play one game, or replay a run by ID
Makefile            # make check, make baselines, make play, make eval, make score
```

Approximate sizes: `world/` ~3000 lines, `agents/` ~1500 lines, tests ~3000 lines. Every file is meant to be readable in one sitting.

## Determinism and replay

A game is fully deterministic given `(seed, action log)`. Every API call lands in `runs/{run_id}/actions.jsonl`; every end-of-day state lands in `runs/{run_id}/states.jsonl`. Replay a recorded run with `python evaluate.py --replay runs/{run_id}`; it asserts byte-identical final state.

## License

MIT. See [LICENSE](LICENSE).

## History

This project began as a 24-hour hackathon scaffold (EAGE Annual 2026 Energy–AI Nexus Hackathon). The original design briefs live under [docs/archive/](docs/archive/) for historical reference. Current docs target the new audience: external agent authors arriving cold.
