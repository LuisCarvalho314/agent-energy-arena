"""Stateful resolver from LLM intents to deterministic API actions."""

from __future__ import annotations

from typing import Any

from agents.llm import ToolCall
from agents.llm_supervisor.actions import (
    Action,
    SurveyAction,
    _config,
    _town_hall_xy,
    action_from_tool_call,
)
from agents.llm_supervisor.memory import SupervisorMemory
from agents.llm_supervisor.policy import has_underfilled_job_asset, job_staffing_gap
from world.catalog import TILE_CATALOG


class SupervisorActionResolver:
    """Resolve abstract tool calls using world state plus private memory."""

    def __init__(self, memory: SupervisorMemory) -> None:
        self.memory = memory

    def from_tool_call(
        self,
        call: ToolCall,
        state_view: dict[str, Any] | None = None,
    ) -> Action | None:
        if call.name == "build" and self._build_blocked_by_underfilled_asset(call, state_view):
            return None
        if call.name == "survey":
            return self._survey(call, state_view)
        return action_from_tool_call(call, state_view)

    def _build_blocked_by_underfilled_asset(
        self,
        call: ToolCall,
        state_view: dict[str, Any] | None,
    ) -> bool:
        if state_view is None:
            raise ValueError("state_view is required when tool call omits coordinates")
        tile_type = str(call.arguments["tile_type"])
        spec = TILE_CATALOG.get(tile_type)
        if spec is None or spec.jobs <= 0:
            return False
        if not has_underfilled_job_asset(state_view):
            return False
        self.memory.mark_job_asset_build_blocked(tile_type, job_staffing_gap(state_view))
        return True

    def _survey(
        self,
        call: ToolCall,
        state_view: dict[str, Any] | None,
    ) -> SurveyAction:
        if state_view is None:
            raise ValueError("state_view is required when tool call omits coordinates")
        size = _clamp_survey_size(call.arguments.get("size", 4))
        x, y = self._next_survey_xy(state_view, size=size)
        return SurveyAction(x=x, y=y, size=size)

    def _next_survey_xy(self, state_view: dict[str, Any], *, size: int) -> tuple[int, int]:
        w, h = _config(state_view)
        for x, y in self._candidate_anchors(state_view, size=size):
            if self.memory.survey_is_new(x, y, size=size, world_w=w, world_h=h):
                return x, y
            self.memory.mark_survey_candidate_blocked()

        margin = max(0, size // 2)
        step = max(1, size)
        for y in range(margin, max(margin + 1, h - margin), step):
            for x in range(margin, max(margin + 1, w - margin), step):
                if self.memory.survey_is_new(x, y, size=size, world_w=w, world_h=h):
                    return x, y
                self.memory.mark_survey_candidate_blocked()

        raise ValueError("no unsurveyed deterministic survey target")

    def _candidate_anchors(
        self,
        state_view: dict[str, Any],
        *,
        size: int,
    ) -> list[tuple[int, int]]:
        w, h = _config(state_view)
        cx, cy = _town_hall_xy(state_view)
        margin = max(0, size // 2)
        offsets = (
            (0, 0),
            (-8, -8),
            (8, -8),
            (-8, 8),
            (8, 8),
            (-8, 0),
            (8, 0),
            (0, -8),
            (0, 8),
            (-12, -12),
            (12, -12),
            (-12, 12),
            (12, 12),
            (-12, 0),
            (12, 0),
            (0, -12),
            (0, 12),
            (-4, -4),
            (4, -4),
            (-4, 4),
            (4, 4),
        )
        anchors: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for dx, dy in offsets:
            x = _clamp(cx + dx, margin, w - margin - 1)
            y = _clamp(cy + dy, margin, h - margin - 1)
            if (x, y) in seen:
                continue
            seen.add((x, y))
            anchors.append((x, y))
        return anchors


def _clamp_survey_size(raw: Any) -> int:
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return 4
    return max(4, min(16, size))


def _clamp(value: int, low: int, high: int) -> int:
    if high < low:
        return low
    return max(low, min(high, value))
