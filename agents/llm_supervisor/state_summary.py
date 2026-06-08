"""Signal-focused state summary for the coordinate-free supervisor."""

from __future__ import annotations

from collections import Counter
from typing import Any

from agents.llm_supervisor.policy import job_staffing_gap, underfilled_job_assets


def summarize_supervisor_state(
    obs: dict[str, Any],
    forecast: list[dict[str, Any]] | None = None,
    memory: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> str:
    """Summarize state as compact decision signals, not raw mechanics."""
    signals = _signals(obs, forecast, memory or {})
    policy = policy or {}
    valid_intents = policy.get("valid_intents") or []
    suppressed_build_types = policy.get("suppressed_build_types") or []
    return "\n".join(
        [
            (
                f"status day={signals['day']}/{signals['game_days']} cash={signals['cash']} "
                f"cash_state={signals['cash_state']} pop={signals['population']} "
                f"housing={signals['housing_capacity']} housing_pressure={signals['housing_pressure']} "
                f"jobs={signals['jobs_total']} unemployed={signals['unemployed']} "
                f"job_headroom={signals['job_headroom']} vacant_jobs={signals['vacant_jobs']} "
                f"underfilled_job_assets={signals['underfilled_job_assets']} "
                f"job_staffing_gap={signals['job_staffing_gap']} "
                f"job_pressure={signals['job_pressure']} "
                f"happy={signals['happiness']} "
                f"happiness_pressure={signals['happiness_pressure']}"
            ),
            (
                f"power demand_peak24={signals['demand_peak24_kw']}kw "
                f"supply_now={signals['supply_now_kw']}kw margin24={signals['power_margin24_kw']}kw "
                f"worst_reserve={signals['worst_reserve_kw']}kw "
                f"worst_reserve_state={signals['worst_reserve_state']} "
                f"power_state={signals['power_state']} renewable_share={signals['renewable_share']} "
                f"renewable_gap={signals['renewable_gap']}"
            ),
            (
                f"city houses={signals['houses']} jobs_tiles={signals['jobs_tiles']} "
                f"parks={signals['parks']} roads={signals['roads']} "
                f"growth_ready={signals['growth_ready']}"
            ),
            (
                f"energy coal={signals['coal']} gas={signals['gas']} solar={signals['solar']} "
                f"wind={signals['wind']} battery={signals['battery']} "
                f"carbon_pressure={signals['carbon_pressure']}"
            ),
            (
                f"oil phase={signals['oil_phase']} surveys={signals['survey_count']} "
                f"revealed_targets={signals['revealed_targets']} drill_ready={signals['drill_ready']} "
                f"best_target_score={signals['best_target_score']} wells={signals['wells']} "
                f"refineries={signals['refineries']} pipelines={signals['pipelines']} "
                f"refinery_need={signals['refinery_need']}"
            ),
            (
                f"memory survey_attempts={signals['memory_survey_attempts']} "
                f"surveyed_columns={signals['memory_surveyed_columns']} "
                f"repeat_survey_blocks={signals['memory_repeat_survey_blocks']} "
                f"job_asset_build_blocks={signals['memory_job_asset_build_blocks']} "
                f"actions_ok={signals['memory_successful_actions']} "
                f"actions_failed={signals['memory_failed_actions']}"
            ),
            f"valid_intents={'; '.join(str(x) for x in valid_intents) or 'none'}",
            (
                "suppressed_build_types="
                f"{','.join(str(x) for x in suppressed_build_types) or 'none'}"
            ),
            f"rate_actions_needed wells={signals['well_rates_needed']} refineries={signals['refinery_rates_needed']}",
            f"needs={','.join(signals['needs']) or 'none'}",
            f"recommended_intents={'; '.join(signals['recommended_intents'])}",
        ]
    )


def _signals(
    obs: dict[str, Any],
    forecast: list[dict[str, Any]] | None,
    memory: dict[str, Any],
) -> dict[str, Any]:
    cfg = obs.get("config") or {}
    tiles = obs.get("tiles") or []
    counts = Counter(str(t.get("type", "?")) for t in tiles)

    cash = float(obs.get("treasury", 0) or 0)
    population = int(obs.get("population", 0) or 0)
    housing_capacity = int(obs.get("housing_capacity", 0) or 0)
    jobs_total = int(obs.get("jobs_total", 0) or 0)
    unemployed = int(obs.get("unemployed", max(0, population - jobs_total)) or 0)
    employed = int(obs.get("employed", max(0, population - unemployed)) or 0)
    vacant_jobs = _vacant_jobs(obs, jobs_total=jobs_total, employed=employed)
    job_headroom = jobs_total - population
    underfilled_assets = underfilled_job_assets(obs)
    staffing_gap = job_staffing_gap(obs)
    happiness = float(obs.get("happiness", 0) or 0)

    demand_peak = _forecast_peak_demand(obs, forecast)
    supply_now = float((obs.get("power_now") or {}).get("supply_kw", 0) or 0)
    power_margin = supply_now - demand_peak
    renewable_share = _renewable_share(obs)
    worst_reserve_margin = float(
        (obs.get("next_24h_preview") or {}).get("min_reserve_margin", 0.0) or 0.0
    )

    top_targets = (obs.get("reservoirs_revealed") or {}).get("top_k") or []
    wells = obs.get("wells") or []
    refineries = [t for t in tiles if t.get("type") == "refinery"]

    survey_count = max(_survey_count(obs), int(memory.get("survey_attempts", 0) or 0))
    oil_phase = _oil_phase(top_targets, wells, refineries, survey_count)
    best_target_score = _best_target_score(top_targets)
    drill_ready = best_target_score >= 2_000_000

    well_rates_needed = sum(1 for w in wells if float(w.get("setpoint_rate_bbl_day", 0) or 0) <= 0)
    refinery_rates_needed = sum(
        1 for r in refineries if float(r.get("setpoint_rate_bbl_day", 0) or 0) <= 0
    )
    refinery_need = bool(wells) and not refineries

    cash_state = _cash_state(cash)
    housing_pressure = _housing_pressure(population, housing_capacity)
    job_pressure = _job_pressure(population, jobs_total, unemployed)
    power_state = _power_state(power_margin)
    renewable_gap = _renewable_gap(renewable_share)
    happiness_pressure = _happiness_pressure(happiness)
    carbon_pressure = _carbon_pressure(counts, renewable_share)
    growth_ready = (
        cash_state in {"healthy", "ample"}
        and power_state in {"balanced", "surplus"}
        and happiness_pressure != "high"
        and housing_pressure != "high"
    )

    worst_reserve_state = _worst_reserve_state(worst_reserve_margin)

    needs = _needs(
        cash_state=cash_state,
        housing_pressure=housing_pressure,
        job_pressure=job_pressure,
        power_state=power_state,
        worst_reserve_state=worst_reserve_state,
        renewable_gap=renewable_gap,
        happiness_pressure=happiness_pressure,
        oil_phase=oil_phase,
        drill_ready=drill_ready,
        well_rates_needed=well_rates_needed,
        refinery_rates_needed=refinery_rates_needed,
    )
    has_refinery = bool(refineries)
    recommendations = _recommendations(needs, cash_state, has_refinery=has_refinery)

    return {
        "day": int(obs.get("day", 0) or 0),
        "game_days": int(cfg.get("active_game_days", cfg.get("game_days", 0)) or 0),
        "cash": _money(cash),
        "cash_state": cash_state,
        "population": population,
        "housing_capacity": housing_capacity,
        "housing_pressure": housing_pressure,
        "jobs_total": jobs_total,
        "unemployed": unemployed,
        "job_headroom": job_headroom,
        "vacant_jobs": vacant_jobs,
        "underfilled_job_assets": len(underfilled_assets),
        "job_staffing_gap": staffing_gap,
        "job_pressure": job_pressure,
        "happiness": _num(happiness, 2),
        "happiness_pressure": happiness_pressure,
        "demand_peak24_kw": _num(demand_peak, 1),
        "supply_now_kw": _num(supply_now, 1),
        "power_margin24_kw": _num(power_margin, 1),
        "worst_reserve_kw": _num(worst_reserve_margin, 3),
        "worst_reserve_state": worst_reserve_state,
        "power_state": power_state,
        "renewable_share": _num(renewable_share, 3),
        "renewable_gap": renewable_gap,
        "houses": counts.get("house", 0),
        "jobs_tiles": counts.get("commercial", 0) + counts.get("industrial", 0),
        "parks": counts.get("park", 0),
        "roads": counts.get("road", 0),
        "growth_ready": str(growth_ready).lower(),
        "coal": counts.get("coal_plant", 0),
        "gas": counts.get("gas_peaker", 0),
        "solar": counts.get("solar_farm", 0),
        "wind": counts.get("wind_turbine", 0),
        "battery": counts.get("battery", 0),
        "carbon_pressure": carbon_pressure,
        "oil_phase": oil_phase,
        "survey_count": survey_count,
        "revealed_targets": len(top_targets),
        "drill_ready": str(drill_ready).lower(),
        "best_target_score": _num(best_target_score, 0),
        "wells": len(wells),
        "refineries": len(refineries),
        "pipelines": counts.get("pipeline", 0),
        "refinery_need": str(refinery_need).lower(),
        "well_rates_needed": well_rates_needed,
        "refinery_rates_needed": refinery_rates_needed,
        "needs": needs,
        "recommended_intents": recommendations,
        "memory_survey_attempts": int(memory.get("survey_attempts", 0) or 0),
        "memory_surveyed_columns": int(memory.get("surveyed_columns", 0) or 0),
        "memory_repeat_survey_blocks": int(
            memory.get("repeated_survey_candidates_blocked", 0) or 0
        ),
        "memory_job_asset_build_blocks": int(memory.get("job_asset_builds_blocked", 0) or 0),
        "memory_successful_actions": int(memory.get("successful_actions", 0) or 0),
        "memory_failed_actions": int(memory.get("failed_actions", 0) or 0),
    }


def _forecast_peak_demand(obs: dict[str, Any], forecast: list[dict[str, Any]] | None) -> float:
    if forecast:
        return max(
            (float(row.get("demand_kw", row.get("demand_factor", 0)) or 0) for row in forecast),
            default=0.0,
        )
    return float((obs.get("power_now") or {}).get("demand_kw", 0) or 0)


def _renewable_share(obs: dict[str, Any]) -> float:
    total = float(obs.get("cumulative_total_served_kwh", 0) or 0)
    renewable = float(obs.get("cumulative_renewable_served_kwh", 0) or 0)
    return renewable / total if total > 0 else 0.0


def _cash_state(cash: float) -> str:
    if cash < 50_000:
        return "critical"
    if cash < 120_000:
        return "tight"
    if cash < 250_000:
        return "healthy"
    return "ample"


def _housing_pressure(population: int, capacity: int) -> str:
    if capacity <= 0:
        return "high"
    ratio = population / capacity
    if ratio >= 0.95:
        return "high"
    if ratio >= 0.80:
        return "medium"
    return "low"


def _job_pressure(population: int, jobs_total: int, unemployed: int) -> str:
    if population <= 0:
        return "low"
    if unemployed >= max(10, population * 0.20) or jobs_total < population:
        return "high"
    if unemployed >= max(5, population * 0.10) or jobs_total <= population:
        return "medium"
    return "low"


def _vacant_jobs(obs: dict[str, Any], *, jobs_total: int, employed: int) -> int:
    if "jobs_vacant" in obs:
        return max(0, int(obs.get("jobs_vacant", 0) or 0))
    return max(0, jobs_total - employed)


def _worst_reserve_state(min_reserve_margin: float) -> str:
    """Classify next-24h worst-hour reserve margin (supply-demand)/demand."""
    if min_reserve_margin < 0:
        return "deficit"
    if min_reserve_margin < 0.10:
        return "stress"
    if min_reserve_margin < 0.20:
        return "tight"
    return "ok"


def _power_state(margin_kw: float) -> str:
    if margin_kw < 0:
        return "deficit"
    if margin_kw < 100:
        return "balanced"
    return "surplus"


def _renewable_gap(share: float) -> str:
    if share < 0.25:
        return "high"
    if share < 0.60:
        return "medium"
    return "low"


def _happiness_pressure(happiness: float) -> str:
    if happiness < 1.00:
        return "high"
    if happiness < 1.10:
        return "medium"
    if happiness < 1.20:
        return "DO NOT BUILD MORE PARKS"
    return "low"


def _carbon_pressure(counts: Counter[str], renewable_share: float) -> str:
    fossil = counts.get("coal_plant", 0) + counts.get("gas_peaker", 0)
    renewable = counts.get("solar_farm", 0) + counts.get("wind_turbine", 0)
    if fossil > renewable or renewable_share < 0.20:
        return "high"
    if fossil > 0 or renewable_share < 0.60:
        return "medium"
    return "low"


def _oil_phase(
    targets: list[dict[str, Any]],
    wells: list[dict[str, Any]],
    refineries: list[dict[str, Any]],
    survey_count: int = 0,
) -> str:
    if not targets and not wells:
        return "surveying" if survey_count > 0 else "not_started"
    if targets and not wells:
        return "ready_to_drill"
    if wells and not refineries:
        return "producing_needs_refinery"
    if wells:
        producers = [w for w in wells if w.get("type") == "production"]
        injectors = [w for w in wells if w.get("type") == "injection"]
        if producers and not injectors:
            return "needs_injection"
        return "operating"
    return "surveying"


def _best_target_score(targets: list[dict[str, Any]]) -> float:
    scores = [
        float(t.get("oil_estimate_bbl", 0) or 0) * float(t.get("perm_estimate_md", 0) or 0)
        for t in targets
    ]
    return max(scores, default=0.0)


def _survey_count(obs: dict[str, Any]) -> int:
    return int(((obs.get("reservoirs_revealed") or {}).get("n_surveys", 0)) or 0)


def _needs(**kwargs: Any) -> list[str]:
    out: list[str] = []
    if kwargs["cash_state"] in {"critical", "tight"}:
        out.append("cash_preserve")
    if kwargs["housing_pressure"] == "high":
        out.append("housing")
    if kwargs["job_pressure"] in {"high", "medium"}:
        out.append("jobs")
    if kwargs["power_state"] == "deficit":
        out.append("power")
    if kwargs["worst_reserve_state"] in {"deficit", "stress"}:
        out.append("reserve_margin")
    if kwargs["renewable_gap"] in {"high", "medium"} and kwargs["cash_state"] != "critical":
        out.append("renewables")
    if kwargs["happiness_pressure"] == "high":
        out.append("happiness")
    if kwargs["well_rates_needed"] or kwargs["refinery_rates_needed"]:
        out.append("rates")
    if kwargs["oil_phase"] == "not_started" and kwargs["cash_state"] in {"healthy", "ample"}:
        out.append("survey")
    if kwargs["drill_ready"] and kwargs["cash_state"] == "ample":
        out.append("drill")
    return out


def _recommendations(
    needs: list[str], cash_state: str, *, has_refinery: bool = False
) -> list[str]:
    if cash_state == "critical":
        return ["step 7"]
    # Gas peakers only dispatch when pipeline-connected to an operational refinery;
    # recommend coal_plant instead until one exists.
    dispatchable_rec = "build gas_peaker" if has_refinery else "build coal_plant"
    mapping = {
        "housing": "build house",
        "jobs": "build commercial",
        "power": dispatchable_rec,
        "reserve_margin": dispatchable_rec,
        "renewables": "build solar_farm",
        "happiness": "build park",
        "rates": "set zero rates",
        "survey": "survey size=4",
        "drill": "drill production",
        "cash_preserve": "step 7",
    }
    recs = []
    for need in needs:
        rec = mapping.get(need)
        if rec is not None and rec not in recs:
            recs.append(rec)
    if "step 7" not in recs:
        recs.append("step 7")
    return recs[:4]


def _money(value: Any) -> str:
    return f"${float(value):,.0f}"


def _num(value: Any, ndigits: int) -> str:
    return str(round(float(value or 0), ndigits))
