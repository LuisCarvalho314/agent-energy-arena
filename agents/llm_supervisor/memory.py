"""Private operational memory for the LLM supervisor.

This state is intentionally separate from the compact state summary sent
to the LLM. The deterministic resolver uses it to avoid repeating
world mutations that are valid API calls but bad strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.llm_supervisor.actions import Action, SurveyAction


@dataclass(frozen=True)
class ActionRecord:
    """Compact audit record for a resolved deterministic action."""

    name: str
    params: dict[str, Any]
    ok: bool
    error: str | None = None


@dataclass
class SupervisorMemory:
    """State used by deterministic planners, not raw LLM context."""

    surveyed_footprints: set[tuple[int, int]] = field(default_factory=set)
    survey_attempts: int = 0
    repeated_survey_candidates_blocked: int = 0
    job_asset_builds_blocked: int = 0
    successful_actions: list[ActionRecord] = field(default_factory=list)
    failed_actions: list[ActionRecord] = field(default_factory=list)

    def reset(self) -> None:
        self.surveyed_footprints.clear()
        self.survey_attempts = 0
        self.repeated_survey_candidates_blocked = 0
        self.job_asset_builds_blocked = 0
        self.successful_actions.clear()
        self.failed_actions.clear()

    def survey_is_new(self, x: int, y: int, *, size: int, world_w: int, world_h: int) -> bool:
        footprint = self._survey_footprint(x, y, size=size, world_w=world_w, world_h=world_h)
        return not any(cell in self.surveyed_footprints for cell in footprint)

    def mark_survey_candidate_blocked(self) -> None:
        self.repeated_survey_candidates_blocked += 1

    def mark_job_asset_build_blocked(self, tile_type: str, staffing_gap: int) -> None:
        self.job_asset_builds_blocked += 1
        self.failed_actions.append(
            ActionRecord(
                name="build",
                params={"tile_type": tile_type, "staffing_gap": staffing_gap},
                ok=False,
                error="job_asset_blocked_with_underfilled_asset",
            )
        )

    def mark_result(
        self,
        action: Action,
        result: dict[str, Any] | None,
        state_view: dict[str, Any] | None = None,
    ) -> None:
        ok = bool(result and result.get("ok"))
        record = ActionRecord(
            name=action.name,
            params=_action_params(action),
            ok=ok,
            error=_result_error(result),
        )
        if ok:
            self.successful_actions.append(record)
            if isinstance(action, SurveyAction):
                self.survey_attempts += 1
                world_w, world_h = _world_size(state_view)
                self.surveyed_footprints.update(
                    self._survey_footprint(
                        action.x,
                        action.y,
                        size=action.size,
                        world_w=world_w,
                        world_h=world_h,
                    )
                )
            return
        self.failed_actions.append(record)

    def summary(self) -> dict[str, Any]:
        last_success = self.successful_actions[-1].name if self.successful_actions else "none"
        last_failure = self.failed_actions[-1].name if self.failed_actions else "none"
        return {
            "survey_attempts": self.survey_attempts,
            "surveyed_columns": len(self.surveyed_footprints),
            "repeated_survey_candidates_blocked": self.repeated_survey_candidates_blocked,
            "job_asset_builds_blocked": self.job_asset_builds_blocked,
            "successful_actions": len(self.successful_actions),
            "failed_actions": len(self.failed_actions),
            "last_success": last_success,
            "last_failure": last_failure,
        }

    def _survey_footprint(
        self,
        x: int,
        y: int,
        *,
        size: int,
        world_w: int,
        world_h: int,
    ) -> set[tuple[int, int]]:
        half = max(0, int(size) // 2)
        start_x = max(0, int(x) - half)
        start_y = max(0, int(y) - half)
        end_x = min(int(world_w), start_x + max(1, int(size)))
        end_y = min(int(world_h), start_y + max(1, int(size)))
        return {(xx, yy) for yy in range(start_y, end_y) for xx in range(start_x, end_x)}


def _action_params(action: Action) -> dict[str, Any]:
    return {
        key: value
        for key, value in vars(action).items()
        if key != "name" and isinstance(value, (str, int, float, bool, type(None)))
    }


def _world_size(state_view: dict[str, Any] | None) -> tuple[int, int]:
    cfg = (state_view or {}).get("config") or {}
    return int(cfg.get("world_w", 32) or 32), int(cfg.get("world_h", 32) or 32)


def _result_error(result: dict[str, Any] | None) -> str | None:
    if result is None:
        return "no_result"
    payload = result.get("result")
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("detail")
        if error is not None:
            return str(error)
    error = result.get("error")
    return str(error) if error is not None else None
