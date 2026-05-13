"""Grid-stress scenario — sustained low-wind weeks + heatwave cluster.

Combines two pressure sources on the dispatch surface:

* Sustained low-wind windows: `state.weather_overrides["wind_speed_mps"]`
  is re-written every hour of every day in each `LOW_WIND_WINDOWS`
  entry so a wind-heavy fleet under-produces for the full window.
  AR(1) wind draws still consume RNG (determinism preserved); the
  override is applied AFTER the draw.
* Heatwave cluster: on each day in `HEATWAVE_DAYS` the scenario
  appends a `heatwave` event to `state.active_events` shaped identically
  to the stochastic sampler's heatwave (severity 1.4, fixed 5-day
  duration). The existing residential-demand × 1.4 and solar-panel
  derate × 0.8 both kick in. The injection runs BEFORE
  `sample_and_apply_events` so the existing "already active" guard
  suppresses the same-day stochastic roll.

All tuning values are class attributes so a maintainer can retune in
review without touching `apply`. The scenario consumes no random
numbers — given `(world, day)` the effect is deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.scenario import Scenario

if TYPE_CHECKING:
    from world.sim import World


class GridStress(Scenario):
    """Stress the grid with low-wind weeks and a heatwave cluster."""

    seed: int = 42

    # Sustained low-wind windows. Each entry is
    # ``(start_day_inclusive, end_day_exclusive, wind_mps)``. The clip
    # is below the wind-turbine cut-in (3 m/s), so wind output is 0
    # for the entire window. AR(1) wind draws still fire; only the
    # observed value is pinned.
    LOW_WIND_WINDOWS: tuple[tuple[int, int, float], ...] = (
        (5, 25, 1.0),
        (180, 200, 1.5),
        (730, 750, 0.8),
    )

    # Heatwave injection schedule. Each day in this tuple triggers a
    # heatwave event identical in shape to the stochastic sampler's
    # version (5-day duration, severity 1.4). Clustering early in the
    # game compounds with the first low-wind window.
    HEATWAVE_DAYS: tuple[int, ...] = (10, 40, 80, 200, 400)
    HEATWAVE_DURATION_DAYS: int = 5
    HEATWAVE_SEVERITY: float = 1.4

    def apply(self, world: World, day: int) -> None:
        state = world.state

        # Low-wind clip. Re-written every day in the window so any
        # mid-window /reset would restore the clip on the next /step.
        # Outside any window, drop the key so the AR(1) draw flows
        # through unchanged.
        active_clip: float | None = None
        starting_today = False
        ending_today = False
        for start, end, mps in self.LOW_WIND_WINDOWS:
            if start <= day < end:
                active_clip = mps
                if day == start:
                    starting_today = True
                break
            if day == end:
                ending_today = True

        if active_clip is not None:
            state.weather_overrides["wind_speed_mps"] = float(active_clip)
            if starting_today:
                state.scenario_trace.append(
                    {
                        "day": day,
                        "kind": "low_wind_start",
                        "wind_mps": float(active_clip),
                    }
                )
        else:
            state.weather_overrides.pop("wind_speed_mps", None)
            if ending_today:
                state.scenario_trace.append({"day": day, "kind": "low_wind_end"})

        # Heatwave injection. Fires once per scheduled day; the
        # "already active" guard prevents a stochastic heatwave on
        # the same day from double-counting (see events.py).
        if day in self.HEATWAVE_DAYS:
            already = any(e.get("type") == "heatwave" for e in state.active_events)
            if not already:
                state.active_events.append(
                    {
                        "type": "heatwave",
                        "started_day": day,
                        "ends_day": day + self.HEATWAVE_DURATION_DAYS,
                        "severity": self.HEATWAVE_SEVERITY,
                    }
                )
                state.scenario_trace.append(
                    {
                        "day": day,
                        "kind": "heatwave_injected",
                        "ends_day": day + self.HEATWAVE_DURATION_DAYS,
                    }
                )
