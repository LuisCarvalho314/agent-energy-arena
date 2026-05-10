"""End-of-game scoring (PRD §"Scoring", brief §8.1 with PRD revisions).

The score is a weighted sum of three independent terms:

  P     = world.population
  T     = world.treasury - STARTING_CASH
  R     = cumulative_renewable_served_kwh / max(cumulative_total_served_kwh, 1)

  p_term = 0.5 * min(P / max(P_ref, 1), 3.0)              # capped at 1.5
  t_term = 0.4 * 0.5 * (1 + tanh(T / max(T_ref, 1)))      # in [0, 0.4]
  r_term = 0.1 * R                                         # in [0, 0.1]

  score  = p_term + t_term + r_term

P_ref / T_ref come from the scripted-agent baseline run on the same seed
(slice 14 generates `baselines/seed_{N}.json`). The renewable share is a
lifetime running sum maintained on WorldState; curtailed kWh exported to
the external grid is excluded from both numerator and denominator.

`score()` is a pure read-only function — it consumes a fully-played
World plus the two baseline references and returns the breakdown dict
the API layer surfaces directly.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from world.sim import World

P_TERM_WEIGHT: float = 0.5
P_TERM_CAP: float = 3.0
T_TERM_WEIGHT: float = 0.4
R_TERM_WEIGHT: float = 0.1


def score(world: World, p_ref: float, t_ref: float) -> dict[str, Any]:
    """Compute the three-term scoring breakdown for a finished game.

    `p_ref` and `t_ref` come from the scripted-agent baseline file for
    the active seed. The function caps the population term at 3× the
    reference per PRD §"Scoring" and saturates the treasury term via
    tanh so very-negative T does not collapse the score below zero.
    """
    s = world.state
    starting_cash = float(world.config.starting_cash)

    P = float(s.population)
    T = float(s.treasury) - starting_cash

    total_served = float(s.cumulative_total_served_kwh)
    renewable_served = float(s.cumulative_renewable_served_kwh)
    R = renewable_served / max(total_served, 1.0)

    p_term = P_TERM_WEIGHT * min(P / max(p_ref, 1.0), P_TERM_CAP)
    t_term = T_TERM_WEIGHT * 0.5 * (1.0 + math.tanh(T / max(t_ref, 1.0)))
    r_term = R_TERM_WEIGHT * R
    total = p_term + t_term + r_term

    return {
        "P": P,
        "P_ref": float(p_ref),
        "p_term": p_term,
        "T": T,
        "T_ref": float(t_ref),
        "t_term": t_term,
        "R": R,
        "r_term": r_term,
        "score": total,
    }
