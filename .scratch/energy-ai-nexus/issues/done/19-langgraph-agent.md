---
Status: needs-triage
---

# 19 — LangGraph reference agent (full-API showcase)

## Parent

[PRD: Energy–AI Nexus Hackathon v1](../PRD.md)

## What to build

A third reference agent at `agents/langgraph_agent.py` built on
[LangGraph](https://langchain-ai.github.io/langgraph/). Where slice 15's
`agents/llm_react.py` is a minimal single-call ReAct loop, this agent is
a **graph-based example** that explicitly walks through the full world
API surface so participants can use it as a how-to for every endpoint.

The agent is a worked example, not a competitive baseline. Optimising
score is out of scope — the goal is "this is how you read the world,
this is how you mutate it, this is how you observe a forecast / event /
reservoir survey result and feed it back into the next decision."

### Graph shape

A LangGraph `StateGraph` with these named nodes, wired in this order
each turn:

1. **observe** — `GET /state` + `GET /forecast` + `GET /events` +
   `GET /reservoirs`. Stores the parsed payloads on the graph state.
2. **summarise** — calls `agents.state_summary.summarize_state(...)` to
   compress observations for the LLM context.
3. **plan** — LLM call with `ACTION_TOOLS` (from `agents.prompts`). The
   model emits one or more tool calls; the agent classifies them as
   "build / demolish / survey / drill / control / step" so each path
   has its own dispatch node.
4. **act** — conditional edge by tool name. Each branch dispatches the
   call via `agents.api_client.ApiClient` and writes the API envelope
   back into graph state for the next turn's prompt:
   - `build` → `POST /build`
   - `demolish` → `POST /demolish`
   - `survey` → `POST /survey`, fetches updated `/reservoirs`
   - `drill` → `POST /drill`
   - `set_well_rate` → `POST /control/well`
   - `set_refinery_rate` → `POST /control/refinery`
5. **step** — `POST /step` with the model-emitted `days` (or fallback
   `days=7` if omitted, mirroring slice 15's behaviour).
6. **loop** — conditional edge: continue to **observe** until
   `state.day >= active_game_days`; otherwise return final state.

The graph definition lives in one file under ~300 lines so the
structure is readable in a single sitting.

### Provider abstraction

Reuse `agents.llm.LLMClient` from slice 15 — same OpenAI / Anthropic /
mock adapters, same `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` env
contract. The LangGraph agent does NOT introduce its own LLM stack;
it wraps the existing `LLMClient.chat(...)` call inside a graph node.

### Demo CLI

`python -m agents.langgraph_agent --seed 42 --days 30` runs a short
30-day demo so participants can see the graph step through every node
type without waiting for a full 3650-day game. A `--full` flag runs
the full game.

### Documentation

A short `docs/agents/langgraph-tour.md` (≤ 1 page) walks through one
turn of the graph, naming each node, the API call it makes, and what
the next node receives. The tour cites file:line locations so a
reader can jump straight to the code.

## Acceptance criteria

- [ ] `agents/langgraph_agent.py` implements the `Agent` protocol from
      `agents/base.py` (constructor `__init__(api, *, seed=None)`,
      `play_game() -> dict`).
- [ ] Dependency on `langgraph` added to `pyproject.toml`'s optional
      `[project.optional-dependencies.llm]` extra (so AFK CI doesn't
      need it but participants who want it install via
      `pip install -e ".[llm]"`).
- [ ] Graph has named nodes: `observe`, `summarise`, `plan`, dispatch
      branches for each of the 6 mutating tools, `step`, and a
      conditional `loop` edge.
- [ ] Every world endpoint is exercised somewhere in the graph:
      `/state`, `/forecast`, `/events`, `/reservoirs`, `/catalog`
      (read once on startup), `/build`, `/demolish`, `/survey`,
      `/drill`, `/control/well`, `/control/refinery`, `/step`,
      `/score` (read once at game end).
- [ ] `python -m agents.langgraph_agent --seed 42 --days 30` runs to
      completion using `MockLLM` when `LLM_API_KEY` is unset (so the
      demo path works offline). Live LLM call activates only when an
      API key is present.
- [ ] `agents/tests/test_langgraph_agent.py` covers: graph compiles,
      observe node fills state correctly, dispatch dispatches the
      correct API call per tool name, step fallback fires when the
      LLM omits `step`, full short-game smoke run with `MockLLM`.
- [ ] `docs/agents/langgraph-tour.md` ≤ 1 page, names each node, and
      cites `agents/langgraph_agent.py:LINE` for each.
- [ ] No regression in `make check` (354 prior tests still pass).
- [ ] The agent does NOT replace `agents/llm_react.py` — both ship.
      Participants choose by editing `submit/agent.py`.

## Out of scope

- Beating the scripted baseline. This is a worked example, not a
  competitive entry. The PRD's >15% target is owned by
  `agents/llm_react.py`.
- LangChain Agents / AgentExecutor abstractions. The point is to show
  the graph topology and per-node API integration, not to layer on
  LangChain's higher-level abstractions.
- Streaming or async. The world API is synchronous; the graph runs
  one turn at a time.
- Persisting graph checkpoints to disk. LangGraph's checkpointer
  feature is interesting but out of scope for a 1-page demo.

## Blocked by

- 15 — LLM ReAct agent (provides `agents/llm.py`, `agents/prompts.py`,
  `agents/state_summary.py` which slice 19 reuses unchanged).
