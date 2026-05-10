"""Refinery economics: refining yield + crude routing.

Implements §4.6 of the brief: each refinery refines up to its setpoint
(capped at REFINERY_MAX_BBL_DAY and at the available crude). Refined
output = actual × REFINERY_YIELD. Surplus crude that no refinery
consumes sells raw at CRUDE_PRICE.

Crude is routed across refineries by descending setpoint (with id
ascending as the deterministic tiebreak), so the agent can prioritise a
high-throughput refinery over a low one without surprises. Process load
(actual × REFINERY_KWH_PER_BBL / 24) is unbilled to the agent — it
counts toward dispatch demand and toward fuel-burn / carbon emissions
on whichever plants serve it, but no retail revenue is paid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.state import Tile

REFINERY_MAX_BBL_DAY: float = 500.0
REFINERY_YIELD: float = 0.85
REFINERY_KWH_PER_BBL: float = 200.0
REFINERY_CO2_PER_BBL: float = 0.30
REFINERY_SETPOINT_MIN: float = 0.0
REFINERY_SETPOINT_MAX: float = REFINERY_MAX_BBL_DAY
REFINED_PRICE_USD_PER_BBL: float = 90.0


def refine_one(setpoint_rate_bbl_day: float, available_crude_bbl: float) -> tuple[float, float]:
    """Run one refinery's daily refining step.

    Returns (actual_input_bbl, refined_bbl). actual is bounded by setpoint,
    available crude, and REFINERY_MAX_BBL_DAY (and floored at 0).
    """
    actual = min(
        float(setpoint_rate_bbl_day),
        float(available_crude_bbl),
        REFINERY_MAX_BBL_DAY,
    )
    actual = max(0.0, actual)
    return actual, actual * REFINERY_YIELD


def route_crude(refineries: list[Tile], total_crude_bbl: float) -> dict[str, float]:
    """Allocate the day's crude across refineries.

    Sort key: (-setpoint_rate_bbl_day, id). The negative-setpoint primary
    key sends crude to the highest-throughput refinery first; id ascending
    is the deterministic tiebreak when two refineries share a setpoint.

    Returns {refinery_id: actual_input_bbl}. Refineries that get no crude
    (either because the queue ran dry or their setpoint was 0) appear with
    actual=0.0 so the caller can pin current_throughput uniformly.
    """
    sorted_refs = sorted(refineries, key=lambda r: (-r.setpoint_rate_bbl_day, r.id))
    available = max(0.0, float(total_crude_bbl))
    per_refinery: dict[str, float] = {}
    for r in sorted_refs:
        actual, _ = refine_one(r.setpoint_rate_bbl_day, available)
        per_refinery[r.id] = actual
        available -= actual
    return per_refinery


def refinery_process_kw(throughput_bbl_day: float) -> float:
    """Refinery hourly process power load: actual × KWH_PER_BBL / 24."""
    return float(throughput_bbl_day) * REFINERY_KWH_PER_BBL / 24.0
