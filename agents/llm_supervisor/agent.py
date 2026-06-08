"""LangGraph reference agent — 5-node graph with a rule-based critic.

```
START → observe → plan(LLM) → critique(rules) → execute → step → {observe | END}
                                     ↑                                  │
                                     └──── re-plan once if all dropped ─┘
```

The five nodes do five different kinds of cognitive work, and the
conditional edge from `critique` back to `plan` gates on a real
decision: did the local critic veto every proposed mutation? If so,
re-prompt the model once with the rejection reasons; otherwise advance
to `execute`. The re-plan retry is capped at 1 per turn.

Two extension surfaces are documented for hackathon participants:

  1. The module-level `RULES = [...]` list of critic functions.
     Append a new pure function `rule(call, state_view)` to add a check.
  2. The rejection-reason prompt construction inside `_plan`. Tune the
     framing the model receives on the re-plan pass.

The critic is a fast local pre-flight check, not a second source of
truth: the `World` still validates and rejects every mutation
server-side (`_execute` swallows those rejections). So the shipped
rules stay cheap and stable — they read the `/state` payload only and
never re-implement `World` economics or topology. That keeps this
file something a student can read top-to-bottom without learning
`World` internals.

CLI:
  python -m agents.langgraph_agent.agent --seed 42 --days 30   # short demo
  python -m agents.langgraph_agent.agent --seed 42 --full      # full game

Requires the active provider's API key (e.g. `ANTHROPIC_API_KEY`) —
same contract as the ReAct CLI.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from agents.api_client import ApiClient
from agents.base import BaseAgent
from agents.llm import LLMClient, LLMResponse, ToolCall, make_llm_from_env
from agents.llm_supervisor.actions import SUPERVISOR_ACTION_TOOLS, Action
from agents.llm_supervisor.memory import SupervisorMemory
from agents.llm_supervisor.policy import build_valid_action_tools, valid_policy_summary
from agents.llm_supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from agents.llm_supervisor.resolver import SupervisorActionResolver
from agents.llm_supervisor.state_summary import summarize_supervisor_state

DEFAULT_STEP_DAYS_FALLBACK: int = 7
MAX_TOKENS_PER_TURN: int = 2048
FORECAST_HOURS: int = 24
MAX_REPLAN_RETRIES: int = 1

MUTATOR_TOOLS: frozenset[str] = frozenset(
    {"build", "demolish", "survey", "drill", "set_well_rate", "set_refinery_rate"}
)


class GraphState(TypedDict, total=False):
    """Per-turn state that flows through the LangGraph nodes."""

    day: int
    game_days: int
    obs: dict[str, Any]
    forecast: list[dict[str, Any]] | None
    pending_calls: list[ToolCall]
    survivors: list[ToolCall]
    rejections: list[str]
    step_days: int
    cumulative_tokens: int
    turn: int
    replan_retries: int


# ---------- Critic rules ---------------------------------------------------
#
# Each rule is a pure function: given the proposed `ToolCall` and the
# world `state_view` (the parsed `/state` payload it would mutate),
# return a rejection reason string or `None` to let the call through.
# The `RULES = [...]` list below is the documented extension surface —
# append your own rule to add a check.

RuleFn = Callable[[ToolCall, dict[str, Any]], "str | None"]


def out_of_bounds(call: ToolCall, state_view: dict[str, Any]) -> str | None:
    """Reject build/demolish/survey/drill calls with an (x, y) outside the world."""
    if call.name not in {"build", "demolish", "survey", "drill"}:
        return None
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 0))
    h = int(cfg.get("world_h", 0))
    try:
        x = int(call.arguments["x"])
        y = int(call.arguments["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if 0 <= x < w and 0 <= y < h:
        return None
    return f"{call.name}({x},{y}) out_of_bounds (world {w}x{h})"


def tile_occupied(call: ToolCall, state_view: dict[str, Any]) -> str | None:
    """Reject `build` calls onto an already-occupied (x, y) surface tile."""
    if call.name != "build":
        return None
    try:
        x = int(call.arguments["x"])
        y = int(call.arguments["y"])
    except (KeyError, TypeError, ValueError):
        return None
    for t in state_view.get("tiles") or []:
        if t.get("x") == x and t.get("y") == y:
            tile_type = call.arguments.get("tile_type")
            return f"build({tile_type},{x},{y}) tile_occupied by {t.get('type')}"
    return None


RULES: list[RuleFn] = [out_of_bounds, tile_occupied]


# ---------- Agent ----------------------------------------------------------


class LangGraphAgent(BaseAgent):
    """Graph-based reference agent. Implements the `Agent` protocol
    (`__init__(api, *, seed=None)` + `play_game() -> dict`).

    Subclasses `BaseAgent` so the Agent Play attach handler accepts it.
    `act(state)` delegates to the shared attach runtime so attach-mode
    behavior matches `LLMReactAgent` exactly. The graph itself only
    runs in CLI mode (`play_game()`).
    """

    def __init__(
        self,
        api: ApiClient,
        *,
        seed: int | None = None,
        llm: LLMClient | None = None,
        system_prompt: str = SUPERVISOR_SYSTEM_PROMPT,
        action_tools: list[dict[str, Any]] | None = None,
        max_tokens_per_turn: int = MAX_TOKENS_PER_TURN,
    ) -> None:
        self.api = api
        self._seed = seed
        self.llm: LLMClient = llm if llm is not None else make_llm_from_env()
        self.system_prompt: str = system_prompt
        self.action_tools: list[dict[str, Any]] = action_tools or SUPERVISOR_ACTION_TOOLS
        self.max_tokens_per_turn: int = max_tokens_per_turn
        self.cumulative_tokens: int = 0
        self.turns: int = 0
        self.final_score: dict[str, Any] | None = None
        self.memory = SupervisorMemory()
        self.resolver = SupervisorActionResolver(self.memory)
        self._last_seen_day: int | None = None
        self.graph = self._build_graph()

    # -- Attach hook ------------------------------------------------------

    def act(self, state: dict[str, Any]) -> int | None:
        self._reset_memory_if_new_game(state)
        forecast = _safe_forecast(self.api)
        tools = build_valid_action_tools(self.action_tools, state, self.memory)
        user_msg = summarize_supervisor_state(
            state,
            forecast,
            self.memory.summary(),
            valid_policy_summary(state, self.memory),
        )
        response = self.llm.chat(
            system=self.system_prompt,
            user=user_msg,
            tools=tools,
            max_tokens=self.max_tokens_per_turn,
        )
        _log_llm_call(
            phase="attach-act",
            system_prompt=self.system_prompt,
            user_msg=user_msg,
            tools=tools,
            response=response,
        )
        skip_days: int | None = None
        state_view = state
        for call in response.tool_calls:
            if call.name == "step":
                if skip_days is None:
                    skip_days = _clamp_days(call.arguments.get("days", DEFAULT_STEP_DAYS_FALLBACK))
                continue
            state_view = self._resolve_execute_and_refresh(call, state_view)
        self.cumulative_tokens += response.usage.total
        self._last_seen_day = int(state_view.get("day", state.get("day", 0)) or 0)
        return skip_days

    # -- Graph construction ----------------------------------------------

    def _build_graph(self) -> Any:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "langgraph is not installed — install the optional 'llm' extra: "
                'pip install -e ".[llm]"'
            ) from exc

        g = StateGraph(GraphState)
        g.add_node("observe", self._observe)
        g.add_node("plan", self._plan)
        g.add_node("critique", self._critique)
        g.add_node("execute", self._execute)
        g.add_node("step", self._step)

        g.add_edge(START, "observe")
        g.add_edge("observe", "plan")
        g.add_edge("plan", "critique")
        g.add_conditional_edges(
            "critique",
            self._route_after_critique,
            {"plan": "plan", "execute": "execute"},
        )
        g.add_edge("execute", "step")
        g.add_conditional_edges(
            "step",
            self._route_after_step,
            {"observe": "observe", "end": END},
        )
        return g.compile()

    # -- Public entry ----------------------------------------------------

    def play_game(self) -> dict[str, Any]:
        """Reset, invoke the graph, then fetch /score for the CLI summary."""
        self.memory.reset()
        self._last_seen_day = None
        self.api.reset(seed=self._seed)
        initial_state = self.api.state()
        game_days = int(
            initial_state["config"].get("active_game_days", initial_state["config"]["game_days"])
        )

        # Recursion limit: roughly (turns × nodes_per_turn) + slack.
        # nodes_per_turn ≈ 6 (observe / plan / critique / execute / step
        # / loop), with one extra plan visit per re-plan retry.
        recursion_limit = max(50, (game_days + 7) * 10)

        final: GraphState = self.graph.invoke(
            {
                "day": int(initial_state.get("day", 0)),
                "game_days": game_days,
                "cumulative_tokens": 0,
                "turn": 0,
                "replan_retries": 0,
            },
            config={"recursion_limit": recursion_limit},
        )

        self.cumulative_tokens = int(final.get("cumulative_tokens", 0))
        self.turns = int(final.get("turn", 0))

        try:
            self.final_score = self.api.score()
        except RuntimeError:
            self.final_score = None

        end_state: dict[str, Any] = final.get("obs") or self.api.state()
        return end_state

    # -- Nodes -----------------------------------------------------------

    def _observe(self, state: GraphState) -> GraphState:
        """Snapshot `/state` + `/forecast`. Resets per-turn rejection state."""
        obs = self.api.state()
        self._reset_memory_if_new_game(obs)
        forecast = _safe_forecast(self.api)
        return {
            "obs": obs,
            "forecast": forecast,
            "day": int(obs.get("day", state.get("day", 0))),
            "rejections": [],
            "replan_retries": 0,
        }

    def _plan(self, state: GraphState) -> GraphState:
        """One LLM call. On a re-plan pass, prepend the rejection reasons
        from `critique` so the model sees what the local critic vetoed."""
        obs = state.get("obs") or {}
        tools = build_valid_action_tools(self.action_tools, obs, self.memory)
        user_msg = summarize_supervisor_state(
            obs,
            state.get("forecast"),
            self.memory.summary(),
            valid_policy_summary(obs, self.memory),
        )
        rejections = state.get("rejections") or []
        if rejections:
            bullets = "\n".join(f"- {r}" for r in rejections)
            user_msg = (
                "Your previous tool calls were ALL rejected by the local critic:\n"
                f"{bullets}\n\nRevise the plan to avoid these failure modes.\n\n" + user_msg
            )

        response = self.llm.chat(
            system=self.system_prompt,
            user=user_msg,
            tools=tools,
            max_tokens=self.max_tokens_per_turn,
        )
        _log_llm_call(
            phase="graph-plan",
            system_prompt=self.system_prompt,
            user_msg=user_msg,
            tools=tools,
            response=response,
        )

        pending: list[ToolCall] = []
        step_days = DEFAULT_STEP_DAYS_FALLBACK
        for call in response.tool_calls:
            if call.name == "step":
                step_days = _clamp_days(call.arguments.get("days", DEFAULT_STEP_DAYS_FALLBACK))
                break  # step terminates the turn — ignore anything after it
            pending.append(call)

        remaining = max(1, state.get("game_days", 0) - state.get("day", 0))
        step_days = min(step_days, remaining)

        retries = int(state.get("replan_retries", 0))
        if rejections:
            retries += 1

        return {
            "pending_calls": pending,
            "step_days": step_days,
            "cumulative_tokens": int(state.get("cumulative_tokens", 0)) + response.usage.total,
            "turn": int(state.get("turn", 0)) + 1,
            "rejections": [],
            "replan_retries": retries,
        }

    def _critique(self, state: GraphState) -> GraphState:
        """Per-call gate. Walks each proposed mutator through `RULES`.
        Calls with non-mutator names are passed through to `execute`,
        which drops them via `dispatch_tool_call` returning `None`
        (defensive against LLM hallucination)."""
        pending = state.get("pending_calls") or []
        state_view = state.get("obs") or {}
        survivors: list[ToolCall] = []
        rejections: list[str] = []
        for call in pending:
            if call.name not in MUTATOR_TOOLS:
                survivors.append(call)
                continue
            reason: str | None = None
            for rule in RULES:
                r = rule(call, state_view)
                if r is not None:
                    reason = r
                    break
            if reason is not None:
                rejections.append(reason)
                continue
            survivors.append(call)
        return {"survivors": survivors, "rejections": rejections}

    def _route_after_critique(self, state: GraphState) -> str:
        """Back-edge to `plan` if every mutator was rejected and we
        haven't already retried this turn; forward to `execute`
        otherwise."""
        pending = state.get("pending_calls") or []
        survivors = state.get("survivors") or []
        rejections = state.get("rejections") or []
        retries = int(state.get("replan_retries", 0))
        full_reject = bool(pending) and not survivors and bool(rejections)
        if full_reject and retries < MAX_REPLAN_RETRIES:
            return "plan"
        return "execute"

    def _execute(self, state: GraphState) -> GraphState:
        """Convert each survivor into a deterministic action, then execute.

        Unknown tool names return `None` from the resolver and
        are silently skipped; world-side rejections (`RuntimeError` from
        the 4xx envelope) and malformed args are swallowed so a single bad
        LLM call doesn't crash the turn.
        """
        survivors = state.get("survivors") or []
        state_view = state.get("obs") or {}
        for call in survivors:
            state_view = self._resolve_execute_and_refresh(call, state_view)
        self._last_seen_day = int(state_view.get("day", state.get("day", 0)) or 0)
        return {"survivors": []}

    def _resolve_execute_and_refresh(
        self,
        call: ToolCall,
        state_view: dict[str, Any],
    ) -> dict[str, Any]:
        action: Action | None = None
        try:
            action = self.resolver.from_tool_call(call, state_view)
            if action is None:
                return state_view
            result = action.execute(self.api)
            self.memory.mark_result(action, result, state_view)
            if result.get("ok"):
                return self.api.state()
        except (RuntimeError, KeyError, TypeError, ValueError):
            if action is not None:
                self.memory.mark_result(action, {"ok": False}, state_view)
        return state_view

    def _reset_memory_if_new_game(self, state: dict[str, Any]) -> None:
        day = int(state.get("day", 0) or 0)
        if day == 0 and self._last_seen_day not in (None, 0):
            self.memory.reset()
        self._last_seen_day = day

    def _step(self, state: GraphState) -> GraphState:
        """Advance the world by `step_days` and refresh `day`."""
        days = max(1, int(state.get("step_days", DEFAULT_STEP_DAYS_FALLBACK)))
        remaining = max(1, state.get("game_days", 0) - state.get("day", 0))
        days = min(days, remaining)
        with contextlib.suppress(RuntimeError):
            self.api.step(days=days)
        new_state = self.api.state()
        return {"obs": new_state, "day": int(new_state.get("day", 0))}

    def _route_after_step(self, state: GraphState) -> str:
        return "observe" if state.get("day", 0) < state.get("game_days", 0) else "end"


# ---------- Helpers --------------------------------------------------------


def _clamp_days(raw: Any) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_STEP_DAYS_FALLBACK
    return max(1, min(7, days))


def _safe_forecast(api: ApiClient) -> list[dict[str, Any]] | None:
    try:
        return api.forecast(hours=FORECAST_HOURS)
    except RuntimeError:
        return None


def _log_llm_call(
    *,
    phase: str,
    system_prompt: str,
    user_msg: str,
    tools: list[dict[str, Any]],
    response: LLMResponse,
) -> None:
    """Log supervisor LLM inputs and normalized outputs.

    Enabled by default for the supervisor because this agent is intended
    to make the LLM/supervisor boundary inspectable. Set
    ``LLM_SUPERVISOR_LOG=0`` to silence it, or ``LLM_SUPERVISOR_LOG_FILE``
    to append JSONL records to a file in addition to stderr. Logs are
    compact by default; set ``LLM_SUPERVISOR_LOG_DETAIL=full`` for full
    prompt/tool dumps.
    """
    enabled = os.environ.get("LLM_SUPERVISOR_LOG", "1").lower() not in {"0", "false", "no"}
    if not enabled:
        return
    detail = os.environ.get("LLM_SUPERVISOR_LOG_DETAIL", "compact").lower()
    payload = (
        _full_llm_log_payload(phase, system_prompt, user_msg, tools, response)
        if detail == "full"
        else _compact_llm_log_payload(phase, system_prompt, user_msg, tools, response)
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(f"\n[llm_supervisor:{phase}]\n{rendered}\n", file=sys.stderr, flush=True)

    log_file = os.environ.get("LLM_SUPERVISOR_LOG_FILE")
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")


def _compact_llm_log_payload(
    phase: str,
    system_prompt: str,
    user_msg: str,
    tools: list[dict[str, Any]],
    response: LLMResponse,
) -> dict[str, Any]:
    lines = user_msg.splitlines()
    return {
        "detail": "compact",
        "phase": phase,
        "system_chars": len(system_prompt),
        "user_chars": len(user_msg),
        "user_head": lines[:8],
        "tools": [
            {
                "name": str(tool.get("name", "")),
                "required": (tool.get("parameters") or {}).get("required", []),
                "properties": sorted(
                    ((tool.get("parameters") or {}).get("properties") or {}).keys()
                ),
            }
            for tool in tools
        ],
        "response": {
            "text_preview": _truncate(response.text, 500),
            "text_chars": len(response.text),
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments} for call in response.tool_calls
            ],
            "usage": _usage_payload(response),
        },
    }


def _full_llm_log_payload(
    phase: str,
    system_prompt: str,
    user_msg: str,
    tools: list[dict[str, Any]],
    response: LLMResponse,
) -> dict[str, Any]:
    return {
        "detail": "full",
        "phase": phase,
        "system": system_prompt,
        "user": user_msg,
        "tools": tools,
        "response": {
            "text": response.text,
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments} for call in response.tool_calls
            ],
            "usage": _usage_payload(response),
        },
    }


def _usage_payload(response: LLMResponse) -> dict[str, int]:
    return {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
        "cache_read_input_tokens": response.usage.cache_read_input_tokens,
        "total": response.usage.total,
    }


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


# ---------- CLI driver -----------------------------------------------------


def _make_inprocess_client() -> ApiClient:
    from fastapi.testclient import TestClient

    from world.api import create_app

    return ApiClient(transport=TestClient(create_app()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LangGraph reference agent (5-node graph).")
    parser.add_argument("--seed", type=int, default=42, help="World seed (default 42).")
    parser.add_argument("--days", type=int, default=30, help="Cap game length (default 30).")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run the full configured game length (overrides --days).",
    )
    parser.add_argument("--api-url", type=str, default=None, help="Live world URL (else in-proc).")
    parser.add_argument("--output", type=Path, default=None, help="Write summary JSON here.")
    args = parser.parse_args(argv)

    if not args.full:
        os.environ["GAME_DAYS"] = str(args.days)
        os.environ["MANUAL_GAME_DAYS"] = str(args.days)

    api = ApiClient(base_url=args.api_url) if args.api_url else _make_inprocess_client()

    # No offline fallback — same contract as the ReAct CLI. Without an
    # LLM key, the construction below raises RuntimeError so a
    # degenerate "step-only" run can't be mistaken for a real one.
    agent = LangGraphAgent(api, seed=args.seed)
    final = agent.play_game()

    payload = {
        "seed": args.seed,
        "day": int(final.get("day", 0)),
        "population": int(final.get("population", 0)),
        "treasury": float(final.get("treasury", 0.0)),
        "turns": agent.turns,
        "cumulative_tokens": agent.cumulative_tokens,
        "score": agent.final_score,
    }
    print(json.dumps(payload, indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
    return 0


# Agent Play attach contract: the handler prefers a top-level `Agent`
# symbol that is a BaseAgent subclass (`world.api.post_agent_attach`).
Agent = LangGraphAgent


if __name__ == "__main__":
    raise SystemExit(main())
