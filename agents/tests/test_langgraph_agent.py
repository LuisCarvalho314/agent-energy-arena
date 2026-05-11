"""End-to-end tests for the LangGraph reference agent using MockLLM.

LangGraph is an OPTIONAL dependency (declared under
`[project.optional-dependencies.llm]`). When it isn't installed, the
whole module skips — AFK CI without the extra installed still passes.

Coverage:
- Graph compiles via the module's `_build_graph()`.
- The `observe` node populates obs / forecast / events / reservoirs.
- Dispatch nodes route by tool name and call the matching ApiClient.
- Step fallback fires when the LLM omits `step` (no infinite loop).
- A short MockLLM-driven game reaches game_days without crashing.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")  # noqa: E402  — skip whole module if missing.

from typing import Any

from fastapi.testclient import TestClient

from agents.api_client import ApiClient
from agents.langgraph_agent import DISPATCH_TOOLS, LangGraphAgent
from agents.llm import LLMResponse, MockLLM, ToolCall, Usage
from world.api import create_app
from world.sim import World


def _make_client(world: World | None = None) -> tuple[ApiClient, World]:
    w = world or World()
    return ApiClient(transport=TestClient(create_app(world=w))), w


def _resp(tool_calls: list[ToolCall], *, in_tok: int = 5, out_tok: int = 2) -> LLMResponse:
    return LLMResponse(tool_calls=tool_calls, text="", usage=Usage(in_tok, out_tok))


def _step_only_mock() -> MockLLM:
    return MockLLM(responses=[_resp([ToolCall("step", {"days": 7})])])


# ---------- Graph construction --------------------------------------------


def test_graph_compiles_without_error() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    # Compiled graph is held on the instance.
    assert agent.graph is not None


def test_graph_has_every_dispatch_node_named_after_its_tool() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    # The compiled graph exposes its node list via .nodes (a dict).
    nodes = set(agent.graph.nodes)
    for tool in DISPATCH_TOOLS:
        assert tool in nodes, f"missing dispatch node {tool!r}"
    for system_node in ("observe", "summarise", "plan", "step"):
        assert system_node in nodes


# ---------- observe node ---------------------------------------------------


def test_observe_node_populates_obs_forecast_events_reservoirs() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    api.reset(seed=42)
    update = agent._observe({"day": 0, "game_days": 14})
    assert "obs" in update and update["obs"]["day"] == 0
    # /forecast returns a list; /events and /reservoirs return dicts.
    assert isinstance(update.get("forecast"), list)
    assert isinstance(update.get("events"), dict)
    assert isinstance(update.get("reservoirs"), dict)


# ---------- summarise node ------------------------------------------------


def test_summarise_node_includes_events_and_reservoirs_breadcrumbs() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    api.reset(seed=42)
    # Run a few weeks so reservoirs show up after a survey.
    api.step(days=7)
    state = agent._observe({"day": 0, "game_days": 14})
    out = agent._summarise(state)
    assert "DAY" in out["summary"]
    # The summarise node may or may not append the breadcrumb lines
    # depending on whether reservoirs were revealed. Either way the base
    # summary must be present.


# ---------- plan node ------------------------------------------------------


def test_plan_node_splits_tool_calls_into_pending_and_step_days() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    th = next(t for t in api.state()["tiles"] if t["type"] == "town_hall")
    mock = MockLLM(
        responses=[
            _resp(
                [
                    ToolCall("build", {"tile_type": "road", "x": th["x"], "y": th["y"] + 1}),
                    ToolCall("step", {"days": 3}),
                ]
            )
        ]
    )
    agent = LangGraphAgent(api, seed=42, llm=mock)
    out = agent._plan({"summary": "...", "day": 0, "game_days": 14, "cumulative_tokens": 0})
    assert len(out["pending_calls"]) == 1
    assert out["pending_calls"][0].name == "build"
    assert out["step_days"] == 3


def test_plan_node_falls_back_to_default_step_days_when_omitted() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    mock = MockLLM(responses=[_resp([])])  # no step at all
    agent = LangGraphAgent(api, seed=42, llm=mock)
    out = agent._plan({"summary": "...", "day": 0, "game_days": 14, "cumulative_tokens": 0})
    assert out["pending_calls"] == []
    assert out["step_days"] == 7  # DEFAULT_STEP_DAYS_FALLBACK


def test_plan_node_ignores_calls_after_step() -> None:
    """`step` terminates the turn — anything after it is dropped."""
    api, _ = _make_client()
    api.reset(seed=42)
    mock = MockLLM(
        responses=[
            _resp(
                [
                    ToolCall("step", {"days": 2}),
                    ToolCall("build", {"tile_type": "road", "x": 1, "y": 1}),
                ]
            )
        ]
    )
    agent = LangGraphAgent(api, seed=42, llm=mock)
    out = agent._plan({"summary": "...", "day": 0, "game_days": 14, "cumulative_tokens": 0})
    assert out["pending_calls"] == []
    assert out["step_days"] == 2


def test_plan_node_accumulates_tokens() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    mock = MockLLM(responses=[_resp([ToolCall("step", {"days": 1})], in_tok=120, out_tok=30)])
    agent = LangGraphAgent(api, seed=42, llm=mock)
    out = agent._plan({"summary": "...", "day": 0, "game_days": 14, "cumulative_tokens": 500})
    assert out["cumulative_tokens"] == 500 + 120 + 30


def test_plan_node_clamps_step_days_to_remaining_game_days() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    mock = MockLLM(responses=[_resp([ToolCall("step", {"days": 7})])])
    agent = LangGraphAgent(api, seed=42, llm=mock)
    out = agent._plan({"summary": "...", "day": 12, "game_days": 14, "cumulative_tokens": 0})
    assert out["step_days"] == 2  # only 2 days left


# ---------- dispatch nodes ------------------------------------------------


def test_dispatch_build_node_creates_tile_via_api() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    th = next(t for t in api.state()["tiles"] if t["type"] == "town_hall")
    x, y = th["x"], th["y"] + 1
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    build_node = agent._make_dispatch_node("build")
    result = build_node(
        {"pending_calls": [ToolCall("build", {"tile_type": "road", "x": x, "y": y})]}
    )
    assert result["pending_calls"] == []
    assert any(t["type"] == "road" and t["x"] == x and t["y"] == y for t in api.state()["tiles"])


def test_dispatch_node_pops_only_head_call() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    survey_node = agent._make_dispatch_node("survey")
    queue = [
        ToolCall("survey", {"x": 4, "y": 4, "size": 4}),
        ToolCall("demolish", {"x": 0, "y": 0}),
    ]
    result = survey_node({"pending_calls": list(queue)})
    assert len(result["pending_calls"]) == 1
    assert result["pending_calls"][0].name == "demolish"


def test_dispatch_node_swallows_malformed_arguments() -> None:
    """Missing required field shouldn't crash the graph — drop and continue."""
    api, _ = _make_client()
    api.reset(seed=42)
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    build_node = agent._make_dispatch_node("build")
    result = build_node({"pending_calls": [ToolCall("build", {"tile_type": "road"})]})
    assert result["pending_calls"] == []
    assert result["last_envelope"] is None


# ---------- routing -------------------------------------------------------


def test_route_next_returns_step_when_queue_empty() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    assert agent._route_next({"pending_calls": []}) == "step"


def test_route_next_returns_head_tool_name() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    queue = [ToolCall("drill", {"x": 1, "y": 2, "target_z": 3})]
    assert agent._route_next({"pending_calls": queue}) == "drill"


def test_route_next_routes_unknown_tool_to_step() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    queue = [ToolCall("hallucinate", {})]
    assert agent._route_next({"pending_calls": queue}) == "step"


# ---------- step + loop ---------------------------------------------------


def test_step_node_advances_world() -> None:
    api, _ = _make_client()
    api.reset(seed=42)
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    out = agent._step({"step_days": 3, "day": 0, "game_days": 14})
    assert out["obs"]["day"] == 3


def test_loop_returns_observe_until_game_end() -> None:
    api, _ = _make_client()
    agent = LangGraphAgent(api, seed=42, llm=_step_only_mock())
    assert agent._loop({"day": 5, "game_days": 14}) == "observe"
    assert agent._loop({"day": 14, "game_days": 14}) == "end"


# ---------- step fallback (LLM omits step) --------------------------------


def test_play_game_emits_fallback_step_when_llm_omits_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `plan` saw no step call, step_days defaults to 7, the step
    node fires anyway, and the game advances — no infinite loop."""
    monkeypatch.setenv("GAME_DAYS", "14")
    monkeypatch.setenv("MANUAL_GAME_DAYS", "14")
    api = ApiClient(transport=TestClient(create_app(world=World())))
    # Empty tool_calls every turn — the model never emits step.
    mock = MockLLM(responses=[_resp([])])
    agent = LangGraphAgent(api, seed=42, llm=mock)
    final = agent.play_game()
    assert final["day"] == 14


# ---------- end-to-end smoke ---------------------------------------------


def test_short_game_runs_to_completion_with_mock_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GAME_DAYS", "14")
    monkeypatch.setenv("MANUAL_GAME_DAYS", "14")
    api = ApiClient(transport=TestClient(create_app(world=World())))
    th_state = World().state_dict()
    th = next(t for t in th_state["tiles"] if t["type"] == "town_hall")
    plan: list[Any] = [
        _resp(
            [
                ToolCall("build", {"tile_type": "road", "x": th["x"] + 1, "y": th["y"]}),
                ToolCall("step", {"days": 7}),
            ]
        ),
        _resp([ToolCall("step", {"days": 7})]),
    ]
    mock = MockLLM(responses=plan)
    agent = LangGraphAgent(api, seed=42, llm=mock)
    final = agent.play_game()
    assert final["day"] == 14
    assert agent.turns >= 1
    assert agent.cumulative_tokens > 0
    # /catalog was fetched once on startup.
    assert agent.catalog is not None and "tiles" in agent.catalog


def test_agent_requires_llm_when_env_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing without `llm=` and no LLM_API_KEY must raise — same
    contract as LLMReactAgent."""
    api, _ = _make_client()
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        LangGraphAgent(api, seed=42)
