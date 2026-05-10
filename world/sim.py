"""Simulation orchestrator.

Owns the deterministic tick loop and the two RNG streams that the rest of the
world will draw from. The skeleton slice has no dynamics yet — the daily loop
exists only to lock in the determinism contract:

  * `sim_rng` advances per **simulated day**, not per `/step` call, so
    `step(days=7)` is byte-identical to `step(days=1)` × 7.
  * `forecast_rng` is an independent child of the master seed, so
    `/forecast` calls never perturb simulation state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from world.config import Config, load_config
from world.state import WorldState


@dataclass
class StepSummary:
    ok: bool
    day_completed: int
    summary: dict[str, Any]
    treasury_after: float


class World:
    def __init__(self, config: Config | None = None, *, session: str = "agent") -> None:
        self.config: Config = config or load_config()
        self.session: str = session
        self.state: WorldState = WorldState(seed=self.config.world_seed)
        self.sim_rng: np.random.Generator
        self.forecast_rng: np.random.Generator
        self.reset(seed=self.config.world_seed)

    # -- Convenience accessors --------------------------------------------

    @property
    def day(self) -> int:
        return self.state.day

    @property
    def hour(self) -> int:
        return self.state.hour

    # -- Lifecycle ---------------------------------------------------------

    def reset(self, seed: int | None = None) -> None:
        seed_used = self.config.world_seed if seed is None else int(seed)
        master = np.random.SeedSequence(seed_used)
        sim_seed, forecast_seed = master.spawn(2)
        self.sim_rng = np.random.default_rng(sim_seed)
        self.forecast_rng = np.random.default_rng(forecast_seed)

        self.state = WorldState(
            seed=seed_used,
            day=0,
            hour=0,
            treasury=float(self.config.starting_cash),
            population=int(self.config.starting_pop),
            happiness=1.0,
        )

    # -- Time advance ------------------------------------------------------

    def step(self, days: int = 7) -> StepSummary:
        if not isinstance(days, int) or days < 1 or days > 7:
            raise ValueError(f"days must be an int in [1, 7]; got {days!r}")

        treasury_start = self.state.treasury
        pop_start = self.state.population

        for _ in range(days):
            self._advance_one_day()

        return StepSummary(
            ok=True,
            day_completed=self.state.day,
            summary={
                "treasury_start": treasury_start,
                "treasury_end": self.state.treasury,
                "delta": self.state.treasury - treasury_start,
                "population_start": pop_start,
                "population_end": self.state.population,
                "happiness": self.state.happiness,
                "events_active": [],
            },
            treasury_after=self.state.treasury,
        )

    def _advance_one_day(self) -> None:
        # The world is empty in the skeleton slice — but the hourly loop and
        # the per-day RNG draw are wired so that adding dynamics later does
        # not change the determinism shape.
        for hour in range(self.config.ticks_per_day):
            self.state.hour = hour
            # placeholder for hourly dynamics; intentionally empty.
        # One mandatory daily draw locks in the "RNG advances per simulated
        # day" contract — even an empty world advances the stream.
        _ = self.sim_rng.standard_normal()
        self.state.day += 1
        self.state.hour = 0

    # -- Forecast (placeholder; uses forecast_rng) -------------------------

    def forecast(self, hours: int = 24) -> dict[str, Any]:
        # Skeleton: emit zero-mean noise from forecast_rng so we can prove
        # this stream is independent from sim_rng.
        noise = self.forecast_rng.standard_normal(int(hours)).tolist()
        return {
            "hours": int(hours),
            "solar_irradiance": [0.0] * int(hours),
            "wind_speed_mps": [0.0] * int(hours),
            "demand_kw": [0.0] * int(hours),
            "noise": noise,
        }

    # -- Read-models -------------------------------------------------------

    def state_dict(self) -> dict[str, Any]:
        s = self.state
        c = self.config
        return {
            "seed": s.seed,
            "day": s.day,
            "hour": s.hour,
            "treasury": s.treasury,
            "population": s.population,
            "happiness": s.happiness,
            "config": {
                "world_w": c.world_w,
                "world_h": c.world_h,
                "world_d": c.world_d,
                "game_days": c.game_days,
                "manual_game_days": c.manual_game_days,
                "ticks_per_day": c.ticks_per_day,
                "carbon_price": c.carbon_price,
                "starting_cash": c.starting_cash,
                "starting_pop": c.starting_pop,
                "session": self.session,
                "active_game_days": (
                    c.manual_game_days if self.session == "manual" else c.game_days
                ),
            },
            "tiles": [],
            "wells": [],
            "reservoirs_revealed": [],
            "active_events": [],
            "weather_now": s.weather_now,
            "power_now": s.power_now,
            "today_summary_so_far": s.today_summary_so_far,
        }
