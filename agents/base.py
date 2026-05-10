"""Agent protocol + a minimal helper class.

`Agent` is the structural type every submission must conform to. The
`BaseAgent` helper handles the reset/observe/act/step loop so concrete
agents only override `act()` and (optionally) `next_step_days()`.

Brief §7.1: `play_game(self) -> dict` plays a complete game and returns
a final score breakdown.
"""

from __future__ import annotations

from typing import Any, Protocol

from agents.api_client import ApiClient


class Agent(Protocol):
    def play_game(self) -> dict[str, Any]: ...


class BaseAgent:
    """Skeleton agent: resets, then loops obs → act → step until game end.

    Subclasses override `act(state)` to submit per-turn actions and
    optionally `next_step_days(state)` to choose a step size between 1
    and 7 days. The default cadence is 7 (one decision per week).
    """

    def __init__(self, api: ApiClient, *, seed: int | None = None) -> None:
        self.api = api
        self._seed = seed

    def play_game(self) -> dict[str, Any]:
        self.api.reset(seed=self._seed)
        state = self.api.state()
        game_days = int(state["config"].get("active_game_days", state["config"]["game_days"]))
        while state["day"] < game_days:
            self.act(state)
            days = max(1, min(7, self.next_step_days(state)))
            remaining = game_days - state["day"]
            if days > remaining:
                days = remaining
            self.api.step(days=days)
            state = self.api.state()
        return state

    # -- Override points --------------------------------------------------

    def act(self, state: dict[str, Any]) -> None:
        """Submit zero or more actions for the current day. No-op by default."""

    def next_step_days(self, state: dict[str, Any]) -> int:
        """Default: weekly cadence."""
        return 7
