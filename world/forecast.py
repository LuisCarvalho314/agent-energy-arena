"""Forecast model (brief §4.9 / slice 12).

`forecast_records(world, hours)` returns a list of `hours` records, one
per future hour `i` (with `i=0` referring to the next hour after the
current one). Each record carries:

  * `hour_offset` — i
  * `solar_irradiance` — `clip(true_solar × (1 + N(0, σ)), 0, 1)`
  * `wind_speed_mps` — `max(0, true_wind + N(0, σ × 5))`
  * `demand_factor` — `true_demand × (1 + N(0, σ × 0.3))`
  * `sigma` — the σ used for that hour (handy for callers/tests)

The noise scales with the forecast horizon:

    σ = 0.05 + 0.25 × (i / hours)

so the next hour has σ=0.05 and the 24-hour horizon has σ ≈ 0.30.

All draws come from `world.forecast_rng`, never `sim_rng` — calling
`/forecast` an arbitrary number of times does not perturb the
simulation. Three forecast_rng draws are consumed per hour, in order
(solar, wind, demand). Resampling is independent and N(0, σ²) so the
mean over many resamples converges to the deterministic truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from world.power import total_demand_kw
from world.weather import irradiance, v_mean

if TYPE_CHECKING:
    from world.sim import World


SIGMA_BASE: float = 0.05
SIGMA_RAMP: float = 0.25
SIGMA_WIND_SCALE: float = 5.0
SIGMA_DEMAND_SCALE: float = 0.3


def sigma_at(i: int, hours: int) -> float:
    """σ for forecast hour i out of `hours`. Brief §4.9."""
    return SIGMA_BASE + SIGMA_RAMP * (float(i) / float(hours))


def _future_day_hour(day_now: int, hour_now: int, i: int) -> tuple[int, int]:
    """Map forecast offset i to a future (day, hour-of-day) pair.

    i=0 is the NEXT hour (current hour + 1), so a forecast issued at
    (D=2, h=23) with i=0 lands on (D=3, h=0).
    """
    total = hour_now + 1 + i
    return day_now + total // 24, total % 24


def _project_truth(world: World, D: int, h: int) -> tuple[float, float, float]:
    """Deterministic baseline (solar, wind, demand) for future (D, h).

    The current cloud_factor is held constant for the projection — it's
    the natural "best guess" for cloudiness over a 24-hour horizon
    (long-run mean is 0.85). Wind uses the seasonal v_mean (long-run
    mean of the AR(1) process). Demand reuses `total_demand_kw` against
    the *current* state, so any active heatwave / demand_surprise
    multipliers are reflected in the projection.
    """
    cloud = world.state.weather_now.cloud_factor
    true_solar = irradiance(D, h, cloud)
    true_wind = v_mean(D, world.wind_phi_seed)
    true_demand = total_demand_kw(world.state, h)
    return true_solar, true_wind, true_demand


def forecast_records(world: World, hours: int) -> list[dict[str, Any]]:
    if not isinstance(hours, int) or hours < 1 or hours > 168:
        raise ValueError(f"hours must be an int in [1, 168]; got {hours!r}")

    rng = world.forecast_rng
    day_now = world.state.day
    hour_now = world.state.hour

    out: list[dict[str, Any]] = []
    for i in range(hours):
        sigma = sigma_at(i, hours)
        D, h = _future_day_hour(day_now, hour_now, i)
        true_solar, true_wind, true_demand = _project_truth(world, D, h)

        n_solar = float(rng.standard_normal())
        n_wind = float(rng.standard_normal())
        n_demand = float(rng.standard_normal())

        solar = max(0.0, min(1.0, true_solar * (1.0 + n_solar * sigma)))
        wind = max(0.0, true_wind + n_wind * sigma * SIGMA_WIND_SCALE)
        demand = true_demand * (1.0 + n_demand * sigma * SIGMA_DEMAND_SCALE)

        out.append(
            {
                "hour_offset": i,
                "solar_irradiance": float(solar),
                "wind_speed_mps": float(wind),
                "demand_factor": float(demand),
                "sigma": float(sigma),
            }
        )
    return out
