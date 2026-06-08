"""Dynamic intent policy for the LLM supervisor."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agents.llm_supervisor.memory import SupervisorMemory
from agents.prompts import TILE_TYPES
from world.catalog import TILE_CATALOG

# --- Scoring constants (mirrors scripted reference agent thresholds) --------
# Validity is the hard constraint layer (valid_build_tile_types).
# Ranking is the soft preference layer (ranked_build_tile_types).
# Score magnitudes are intentionally approximate; relative order is what matters.

BATTERY_CAPEX: float = 60_000.0
MAX_BATTERIES: int = 4
HOUSING_HEADROOM: int = 30
JOBS_HEADROOM: int = 20
MIN_TREASURY_BUILD: float = 50_000.0
COAL_DEMOLISH_CARBON_USD: float = 80.0

# Housing proximity thresholds for happiness-halo penalties (density-based proxy).
# Used for coal/gas where the perimeter placer has limited site control.
_HOUSING_PROX_MOD: int = 8   # n_houses where placement near housing becomes likely
_HOUSING_PROX_HIGH: int = 15  # n_houses where proximity risk is significant

# Spatial separation constants (Chebyshev geometry).
# Industrial, coal, gas, and refinery impose a happiness halo up to radius 2.
# A clearance of >= 3 keeps housing outside that halo.
# Road expansion bonuses are capped so roads never outrank grid/storage builds.
_SAFETY_RADIUS: int = 3              # min Chebyshev clearance: housing←→hazard or industrial←→houses
_ROAD_EXPANSION_SCALE: float = 50.0  # score per clearance unit above _SAFETY_RADIUS
_ROAD_MAX_SCORE: float = 499.0       # ceiling: roads stay below refinery (500) and battery (600)
_SAFE_SITE_BONUS: float = 30.0       # bonus when a geometry-safe build site exists
_UNSAFE_SITE_PENALTY_HOUSING: float = 100.0    # penalty when no safe housing site
_UNSAFE_SITE_PENALTY_INDUSTRIAL: float = 80.0  # penalty when no safe industrial site
# Commercial becomes preferred jobs asset when industrial cannot be safely placed.
_INDUSTRIAL_CONSTRAINED_COMMERCIAL_BONUS: float = 40.0

# Tile types that create happiness hazards for nearby housing.
_HOUSING_HAZARD_TYPES: frozenset[str] = frozenset(
    {"coal_plant", "gas_peaker", "industrial", "refinery"}
)

# --- Demolition scoring constants -------------------------------------------
# Demolition returns 25% of capex — it destroys 75% of invested capital.
# The default penalty reflects this: demolition must be strongly justified.

_DEMOLISH_DEFAULT_PENALTY: float = -200.0
_DEMOLISH_CARBON_TRANSITION_BOOST: float = 300.0  # condition 1: carbon price + replacement gen
_DEMOLISH_CRISIS_BOOST: float = 100.0             # condition 4: blackout/heatwave last resort
_DEMOLISH_REVENUE_PENALTY: float = -150.0         # commercial / industrial / refinery / prod well
_DEMOLISH_CONSTRAINED_HOUSING_PENALTY: float = -250.0  # house when capacity already tight
_DEMOLISH_ROAD_PENALTY: float = -50.0             # road (unless clearly redundant)
_DEMOLISH_RENEWABLE_PENALTY: float = -150.0       # solar / wind

# Tile types that are absolutely never scored as demolition candidates.
_DEMOLISH_NEVER: frozenset[str] = frozenset({"town_hall", "park"})
# Tiles that produce revenue / income every day — large penalty to demolish.
_DEMOLISH_REVENUE_TYPES: frozenset[str] = frozenset(
    {"commercial", "industrial", "refinery"}
)
_DEMOLISH_RENEWABLE_TYPES: frozenset[str] = frozenset({"solar_farm", "wind_turbine"})

# --- Road-network preservation constants ------------------------------------
# When nearly all road-adjacent build slots are also critical road-extension
# tiles, placing an ordinary asset there consumes the expansion corridor.
# Penalties drop house/jobs builds; the road bonus lifts road above them.
# Emergency grid assets (gas_peaker/coal_plant/battery) are never penalised —
# they already outscore road at 700-1000 and power trumps connectivity.
_BUILD_CROWDS_ROAD_HOUSE_PENALTY: float = -150.0
_BUILD_CROWDS_ROAD_JOBS_PENALTY: float = -120.0
_CRITICAL_ROAD_EXPANSION_BONUS: float = 300.0


# --- Public API -------------------------------------------------------------


def build_valid_action_tools(
    base_tools: list[dict[str, Any]],
    state_view: dict[str, Any],
    memory: SupervisorMemory,
) -> list[dict[str, Any]]:
    """Return tool schemas narrowed to currently valid intents.

    The build enum is ranked by priority (top 5) rather than unordered,
    so the LLM sees the most useful tile types first.
    """
    valid_names = set(valid_tool_names(state_view, memory))
    out: list[dict[str, Any]] = []
    for tool in deepcopy(base_tools):
        name = str(tool.get("name", ""))
        if name not in valid_names:
            continue
        if name == "build":
            ranked = top_ranked_build_tile_types(state_view, limit=5)
            if not ranked:
                continue
            params = tool.setdefault("parameters", {})
            props = params.setdefault("properties", {})
            props.setdefault("tile_type", {})["enum"] = ranked
        out.append(tool)
    return out


def valid_policy_summary(state_view: dict[str, Any], memory: SupervisorMemory) -> dict[str, Any]:
    build_types = valid_build_tile_types(state_view)
    intents = [f"build {tile_type}" for tile_type in build_types]
    if "survey" in valid_tool_names(state_view, memory):
        intents.append("survey size=4")
    if "drill" in valid_tool_names(state_view, memory):
        intents.append("drill production")
    intents.append("step 1..7")
    return {
        "valid_build_types": build_types,
        "valid_intents": intents,
        "suppressed_build_types": suppressed_build_tile_types(state_view),
        "ranked_build_types": ranked_build_tile_types(state_view),
        "demolish_score": demolish_score(state_view),
    }


def valid_tool_names(state_view: dict[str, Any], memory: SupervisorMemory) -> list[str]:
    names = ["step"]
    if valid_build_tile_types(state_view):
        names.append("build")
    if _has_demolish_target(state_view) and demolish_score(state_view)["score"] > 0:
        names.append("demolish")
    if _has_unsurveyed_capacity(state_view, memory):
        names.append("survey")
    if _top_targets(state_view):
        names.append("drill")
    if state_view.get("wells") or []:
        names.append("set_well_rate")
    if _refineries(state_view):
        names.append("set_refinery_rate")
    return names


def valid_build_tile_types(state_view: dict[str, Any]) -> list[str]:
    has_underfilled = has_underfilled_job_asset(state_view)
    out: list[str] = []
    for tile_type in TILE_TYPES:
        spec = TILE_CATALOG.get(tile_type)
        if spec is None or not spec.buildable:
            continue
        if has_underfilled and spec.jobs > 0:
            continue
        out.append(tile_type)
    return out


def ranked_build_tile_types(state_view: dict[str, Any]) -> list[dict[str, Any]]:
    """Score valid build types using scripted-agent priority heuristics.

    Validity (valid_build_tile_types) is the hard constraint layer —
    only already-valid types are scored here.  This is the soft preference
    layer: scores mirror the scripted reference agent's decision tree but
    are intentionally approximate.  Priority order:
      crisis/grid stability > reserve margin > battery/storage >
      coal retirement > oil loop/refinery > housing/jobs > road expansion.
    """
    valid = set(valid_build_tile_types(state_view))
    if not valid:
        return []

    phase = _phase(state_view)
    treasury = float(state_view.get("treasury", 0) or 0)
    pop = int(state_view.get("population", 0) or 0)

    n_solar = _tile_count(state_view, "solar_farm")
    n_wind = _tile_count(state_view, "wind_turbine")
    n_battery = _tile_count(state_view, "battery")
    n_commercial = _tile_count(state_view, "commercial")
    n_industrial = _tile_count(state_view, "industrial")
    n_refinery = _tile_count(state_view, "refinery")
    n_houses = _tile_count(state_view, "house")
    n_prod_wells = sum(
        1 for w in (state_view.get("wells") or []) if w.get("type") == "production"
    )
    n_renewable = n_solar + n_wind

    disp = _dispatchable_kw(state_view)
    peak = _expected_peak_kw(state_view)
    cap = _housing_capacity(state_view)
    jobs = _jobs(state_view)
    events = _active_event_types(state_view)
    had_stress = _had_power_stress(state_view)
    is_blackout = (state_view.get("power_now") or {}).get("balance_state") == "blackout"
    need_dispatch = disp < 1.3 * peak or had_stress

    # Spatial safety flags — geometry only, computed once before the scoring loop.
    # Safe site = an empty road-adjacent cell clear of the relevant hazard radius.
    has_safe_housing = _has_safe_housing_site(state_view)
    has_safe_industrial = _has_safe_industrial_site(state_view)

    # Road-network preservation: identify critical extension tiles and whether
    # placing an ordinary asset would consume the last useful expansion corridor.
    critical_road_tiles = _critical_road_extension_tiles(state_view)
    road_adjacent_cells = _empty_road_adjacent_cells(state_view)
    non_critical_slots = sum(1 for c in road_adjacent_cells if c not in critical_road_tiles)
    # Trigger only when critical tiles exist and almost no alternative slots remain.
    build_crowds_road = bool(critical_road_tiles) and non_critical_slots <= 1

    result: list[dict[str, Any]] = []
    for tile_type in valid:
        score = 0.0
        reasons: list[str] = []

        if tile_type == "gas_peaker":
            # Gas peakers only dispatch when pipeline-connected to an operational
            # refinery — building one without a refinery wastes the capex.
            if n_refinery >= 1:
                if "heatwave" in events or is_blackout:
                    score = 1000.0
                    reasons.append("crisis: active heatwave or blackout")
                elif need_dispatch and treasury >= 80_000:
                    score = 700.0
                    reasons.append("reserve margin stress: gas_peaker ramps fast")
                if score > 0 and n_houses >= _HOUSING_PROX_MOD:
                    penalty = 30.0 if n_houses >= _HOUSING_PROX_HIGH else 15.0
                    score -= penalty
                    reasons.append(f"housing proximity: -{penalty:.0f} happiness-halo risk")

        elif tile_type == "coal_plant":
            if need_dispatch and peak > 1_000.0 and treasury >= 200_000 and phase != "late":
                score = 800.0
                reasons.append("reserve margin: high load, coal preferred for baseload")
                if n_houses >= _HOUSING_PROX_MOD:
                    penalty = 40.0 if n_houses >= _HOUSING_PROX_HIGH else 20.0
                    score -= penalty
                    reasons.append(f"housing proximity: -{penalty:.0f} happiness-halo risk")

        elif tile_type == "battery":
            target = min(MAX_BATTERIES, n_renewable // 2)
            if n_renewable >= 1 and n_battery < target and treasury >= BATTERY_CAPEX:
                score = 600.0
                reasons.append(
                    f"storage: {n_battery}/{target} batteries for {n_renewable} renewables"
                )

        elif tile_type == "refinery":
            if (
                phase in ("diversify", "mature", "late")
                and n_prod_wells >= 2
                and n_refinery == 0
                and treasury >= 150_000
            ):
                score = 500.0
                reasons.append("oil loop: 2+ production wells, no refinery yet")

        elif tile_type == "house":
            cap_short = cap <= pop + HOUSING_HEADROOM
            not_saturated = phase != "late" or pop <= 0.9 * cap
            if cap_short and not_saturated and treasury >= MIN_TREASURY_BUILD:
                score = 450.0
                reasons.append(f"housing short: capacity {cap} ≤ pop {pop} + {HOUSING_HEADROOM}")
                # Spatial hard preference: housing should not be placed near industrial hazards.
                # Bonus when a safe site exists; penalty (and road expansion) when it doesn't.
                if has_safe_housing:
                    score += _SAFE_SITE_BONUS
                    reasons.append("safe housing site available: clear of industrial/coal/gas/refinery")
                else:
                    score -= _UNSAFE_SITE_PENALTY_HOUSING
                    reasons.append("no safe housing site currently available")
                # Road-network preservation: placing a house on the last road-extension
                # corridor permanently forecloses future spatial options.
                if build_crowds_road:
                    score += _BUILD_CROWDS_ROAD_HOUSE_PENALTY
                    reasons.append("road should be built first to preserve expansion corridor")

        elif tile_type == "commercial":
            jobs_short = jobs <= pop + JOBS_HEADROOM
            power_ok = disp >= 1.2 * peak
            if jobs_short and power_ok and treasury >= MIN_TREASURY_BUILD:
                score = 380.0
                reasons.append(f"jobs short: {jobs} ≤ pop {pop} + {JOBS_HEADROOM}")
                if treasury < 120_000:
                    score += 25.0
                    reasons.append("treasury tight: prefer low-capex commercial ($8k)")
                if need_dispatch:
                    score += 20.0
                    reasons.append("power tight: commercial adds only 50kW peak vs 300kW continuous")
                if n_houses >= _HOUSING_PROX_MOD:
                    score += 15.0
                    reasons.append("housing dense: commercial earns from nearby houses")
                # When industrial cannot be safely placed, commercial is the preferred jobs asset.
                # It has no happiness halo and lower power demand.
                if not has_safe_industrial:
                    score += _INDUSTRIAL_CONSTRAINED_COMMERCIAL_BONUS
                    reasons.append("industrial spatially constrained: commercial preferred for jobs")
                if build_crowds_road:
                    score += _BUILD_CROWDS_ROAD_JOBS_PENALTY
                    reasons.append("road should be built first to preserve expansion corridor")

        elif tile_type == "industrial":
            jobs_short = jobs <= pop + JOBS_HEADROOM
            jobs_significantly_short = jobs < pop
            power_ok = disp >= 1.2 * (peak + 300.0)
            phase_ok = phase in ("buildout", "diversify", "mature")
            if jobs_short and power_ok and phase_ok and treasury >= 20_000:
                score = 380.0
                reasons.append("jobs short: industrial when power margin comfortable")
                if jobs_significantly_short:
                    score += 50.0
                    reasons.append("jobs critically short: industrial +30 jobs/tile vs commercial +12")
                if not need_dispatch:
                    score += 20.0
                    reasons.append("grid stable: safe to add 300kW continuous load")
                # Spatial hard preference: industrial must not be placed near housing.
                # Bonus when a clear site exists; penalty otherwise (defer to commercial or road).
                if has_safe_industrial:
                    score += _SAFE_SITE_BONUS
                    reasons.append("safe industrial site available: clear of housing")
                else:
                    score -= _UNSAFE_SITE_PENALTY_INDUSTRIAL
                    reasons.append("no safe industrial site currently available")
                if build_crowds_road:
                    score += _BUILD_CROWDS_ROAD_JOBS_PENALTY
                    reasons.append("road should be built first to preserve expansion corridor")

        elif tile_type == "wind_turbine":
            if (
                phase in ("mature", "late")
                and not need_dispatch
                and (n_solar + 1) < (n_commercial + n_industrial * 2)
                and treasury >= 500_000
            ):
                score = 300.0
                reasons.append("renewables: mature phase, comfortable dispatch margin")

        elif tile_type == "solar_farm":
            if phase in ("bootstrap", "buildout"):
                score = 250.0
                reasons.append("bootstrap resilience: early solar generation")
            elif not need_dispatch:
                score = 150.0
                reasons.append("solar: supplement renewables when margin comfortable")

        elif tile_type == "pipeline":
            if n_prod_wells >= 1 and n_refinery >= 1:
                score = 200.0
                reasons.append("oil loop: connect producer to refinery")

        elif tile_type == "road":
            cap_short = cap <= pop + HOUSING_HEADROOM
            jobs_short = jobs <= pop + JOBS_HEADROOM
            if cap_short or jobs_short:
                score = 100.0
                reasons.append("road: expand build slots for housing/jobs")
                # Road expansion is a strategic enabling action: building a road can unlock
                # future build sites that are farther from hazards than any current site.
                # Only apply when the corresponding safe site is absent (otherwise the
                # direct build is preferable to waiting for road expansion).
                if cap_short and not has_safe_housing:
                    h_exp = housing_road_expansion_score(state_view)
                    if h_exp > 0:
                        score += h_exp
                        reasons.append(f"road unlocks safer housing site: +{h_exp:.0f}")
                if jobs_short and not has_safe_industrial:
                    i_exp = industrial_road_expansion_score(state_view)
                    if i_exp > 0:
                        score += i_exp
                        reasons.append(f"road unlocks safer industrial site: +{i_exp:.0f}")
                # Network preservation: critical extension tiles exist and placing an
                # ordinary asset would consume the last open expansion corridor.
                if build_crowds_road:
                    score += _CRITICAL_ROAD_EXPANSION_BONUS
                    reasons.append(
                        f"critical road expansion: {len(critical_road_tiles)} strategic "
                        "tile(s) — building first preserves future placement options"
                    )
                # Hard cap: roads must never outrank grid stability, storage, or oil-loop builds.
                if score > _ROAD_MAX_SCORE:
                    score = _ROAD_MAX_SCORE

        elif tile_type == "park":
            score = 50.0
            reasons.append("park: happiness boost")

        result.append({"tile_type": tile_type, "score": score, "reasons": reasons})

    result.sort(key=lambda d: float(d["score"]), reverse=True)
    return result


def top_ranked_build_tile_types(
    state_view: dict[str, Any],
    limit: int = 5,
) -> list[str]:
    """Top ``limit`` tile types in descending priority order.

    Falls back to valid_build_tile_types if ranking raises or returns empty.
    """
    try:
        ranked = ranked_build_tile_types(state_view)
        types = [str(d["tile_type"]) for d in ranked if float(d["score"]) > 0]
        if types:
            return types[:limit]
    except Exception:  # noqa: BLE001
        pass
    return valid_build_tile_types(state_view)[:limit]


def demolish_score(state_view: dict[str, Any]) -> dict[str, Any]:
    """Score demolition as a valid action.  Default is -200 (heavily negative).

    Demolition returns only 25% of capex, so 75% of invested capital is lost.
    The burden of proof is therefore much higher than for construction.  This
    function evaluates every non-protected candidate tile and returns the score
    of the best-justified demolition option.  A score > 0 is required before
    the 'demolish' tool is shown to the LLM.

    Justified conditions (score boosters):
      1. Carbon transition  — coal_plant + high carbon price + replacement gen
      4. Crisis recovery    — blackout/heatwave as last resort

    Additional penalties reduce the score for value-destroying targets:
      - Revenue-producing assets (commercial / industrial / refinery)
      - Housing when capacity is constrained
      - Renewable generation
      - Roads
    """
    base = _DEMOLISH_DEFAULT_PENALTY
    candidates = [
        t
        for t in (state_view.get("tiles") or [])
        if t.get("type") not in _DEMOLISH_NEVER
        and float(t.get("capex_paid", 0) or 0) > 0
    ]
    if not candidates:
        return {"score": base, "reasons": ["no valid demolition candidates"]}

    carbon_price = float(state_view.get("carbon_price", 0) or 0)
    n_gas = _tile_count(state_view, "gas_peaker")
    n_solar = _tile_count(state_view, "solar_farm")
    n_wind = _tile_count(state_view, "wind_turbine")
    is_blackout = (state_view.get("power_now") or {}).get("balance_state") == "blackout"
    events = _active_event_types(state_view)
    in_crisis = is_blackout or "heatwave" in events
    cap = _housing_capacity(state_view)
    pop = int(state_view.get("population", 0) or 0)
    cap_constrained = cap <= pop + HOUSING_HEADROOM
    # Replacement generation: an alternative dispatchable or two renewables exist.
    replacement_gen = n_gas >= 1 or (n_solar + n_wind) >= 2

    best_score = base
    best_reasons: list[str] = ["default: demolition destroys 75% of capital; requires justification"]

    for tile in candidates:
        tile_type = str(tile.get("type", ""))
        t_score = base
        t_reasons: list[str] = []

        # --- Justified condition 1: carbon transition ---
        # Coal plant contributes ongoing CO2 cost when carbon price is high
        # and replacement generation already exists to cover the capacity gap.
        if (
            tile_type == "coal_plant"
            and carbon_price >= COAL_DEMOLISH_CARBON_USD
            and replacement_gen
        ):
            t_score += _DEMOLISH_CARBON_TRANSITION_BOOST
            t_reasons.append(
                f"carbon transition: coal_plant at ${carbon_price:.0f}/tCO2, "
                "replacement generation in place"
            )

        # --- Justified condition 4: crisis recovery ---
        # Last resort only — non-revenue tiles blocking critical construction.
        # Revenue-producing assets are excluded: destroying income during a
        # crisis makes recovery harder, not easier.
        if in_crisis and tile_type not in _DEMOLISH_REVENUE_TYPES:
            t_score += _DEMOLISH_CRISIS_BOOST
            t_reasons.append("crisis recovery: demolition frees capital or space during emergency")

        # --- Additional penalties ---

        # Revenue-producing assets generate daily income; destroying them
        # compounds the capital loss with lost future revenue.
        if tile_type in _DEMOLISH_REVENUE_TYPES:
            t_score += _DEMOLISH_REVENUE_PENALTY
            t_reasons.append(f"large penalty: {tile_type} produces daily revenue")

        # Production wells are also revenue assets (treated like refinery).
        if tile_type == "oil_well" and str(tile.get("well_type", "")) == "production":
            t_score += _DEMOLISH_REVENUE_PENALTY
            t_reasons.append("large penalty: production well generates daily oil revenue")

        # Housing demolition when capacity is already tight evicts residents
        # and collapses population, triggering a downward happiness spiral.
        if tile_type == "house" and cap_constrained:
            t_score += _DEMOLISH_CONSTRAINED_HOUSING_PENALTY
            t_reasons.append("very large penalty: housing capacity already constrained")

        # Renewable generation has no ongoing fuel cost; replacing it requires
        # full capex again with no incremental efficiency benefit.
        if tile_type in _DEMOLISH_RENEWABLE_TYPES:
            t_score += _DEMOLISH_RENEWABLE_PENALTY
            t_reasons.append(f"large penalty: {tile_type} is zero-marginal-cost generation")

        # Road demolition can disconnect entire neighbourhoods from build slots.
        if tile_type == "road":
            t_score += _DEMOLISH_ROAD_PENALTY
            t_reasons.append("moderate penalty: road removal may disrupt build-site connectivity")

        if t_score > best_score:
            best_score = t_score
            best_reasons = t_reasons

    return {"score": best_score, "reasons": best_reasons}


def suppressed_build_tile_types(state_view: dict[str, Any]) -> list[str]:
    if not has_underfilled_job_asset(state_view):
        return []
    out: list[str] = []
    for tile_type in TILE_TYPES:
        spec = TILE_CATALOG.get(tile_type)
        if spec is not None and spec.buildable and spec.jobs > 0:
            out.append(tile_type)
    return out


def has_underfilled_job_asset(state_view: dict[str, Any]) -> bool:
    return bool(underfilled_job_assets(state_view))


def underfilled_job_assets(state_view: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for item in list(state_view.get("tiles") or []) + list(state_view.get("wells") or []):
        jobs_cap = _item_jobs(item)
        if jobs_cap <= 0:
            continue
        staffed = int(item.get("staffed_jobs", 0) or 0)
        if staffed < jobs_cap:
            assets.append(
                {
                    "id": str(item.get("id", "")),
                    "type": str(item.get("type", "")),
                    "jobs": jobs_cap,
                    "staffed_jobs": staffed,
                    "gap": jobs_cap - staffed,
                }
            )
    return assets


def job_staffing_gap(state_view: dict[str, Any]) -> int:
    return sum(int(asset["gap"]) for asset in underfilled_job_assets(state_view))


# --- State helpers ----------------------------------------------------------
# These mirror the scripted reference agent's approximations and read the
# /state payload only — they never reimplement World internals.


def _phase(state_view: dict[str, Any]) -> str:
    day = int(state_view.get("day", 0) or 0)
    if day < 28:
        return "bootstrap"
    if day < 26 * 7:
        return "buildout"
    if day < 104 * 7:
        return "diversify"
    if day < 260 * 7:
        return "mature"
    return "late"


def _tile_count(state_view: dict[str, Any], tile_type: str) -> int:
    return sum(1 for t in (state_view.get("tiles") or []) if t.get("type") == tile_type)


def _housing_capacity(state_view: dict[str, Any]) -> int:
    return sum(
        int(t.get("housing_capacity", 0) or 0) for t in (state_view.get("tiles") or [])
    )


def _jobs(state_view: dict[str, Any]) -> int:
    return sum(int(t.get("jobs", 0) or 0) for t in (state_view.get("tiles") or []))


def _dispatchable_kw(state_view: dict[str, Any]) -> float:
    """Gas + coal nameplate only — renewables don't count toward reserve at peak."""
    return (
        _tile_count(state_view, "gas_peaker") * 500.0
        + _tile_count(state_view, "coal_plant") * 1500.0
    )


def _expected_peak_kw(state_view: dict[str, Any]) -> float:
    """Evening peak estimate: residential + commercial + continuous industrial."""
    pop = int(state_view.get("population", 0) or 0)
    return (
        pop * 0.333 * 1.5
        + _tile_count(state_view, "commercial") * 50.0
        + _tile_count(state_view, "industrial") * 300.0
    )


def _had_power_stress(state_view: dict[str, Any]) -> bool:
    hourly = state_view.get("last_day_balance_state_by_hour") or []
    return any(s in ("brownout", "blackout") for s in hourly)


def _active_event_types(state_view: dict[str, Any]) -> set[str]:
    return {str(e.get("type", "")) for e in (state_view.get("active_events") or [])}


# --- Internals --------------------------------------------------------------


def _has_demolish_target(state_view: dict[str, Any]) -> bool:
    for tile in state_view.get("tiles") or []:
        if tile.get("type") == "town_hall":
            continue
        if float(tile.get("capex_paid", 0) or 0) > 0:
            return True
    return False


def _has_unsurveyed_capacity(state_view: dict[str, Any], memory: SupervisorMemory) -> bool:
    if int(state_view.get("day", 0) or 0) < 100:
        return False
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    return len(memory.surveyed_footprints) < w * h


def _top_targets(state_view: dict[str, Any]) -> list[dict[str, Any]]:
    return (state_view.get("reservoirs_revealed") or {}).get("top_k") or []


def _refineries(state_view: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in state_view.get("tiles") or [] if t.get("type") == "refinery"]


def _item_jobs(item: dict[str, Any]) -> int:
    if "jobs" in item:
        return int(item.get("jobs", 0) or 0)
    spec = TILE_CATALOG.get(str(item.get("type", "")))
    return int(spec.jobs) if spec is not None else 0


# --- Spatial helpers ---------------------------------------------------------
# Geometry-only, no simulation rollouts.  All use Chebyshev distance so that
# diagonal adjacency (radius-2 happiness halos) is measured correctly.


def _empty_road_adjacent_cells(state_view: dict[str, Any]) -> list[tuple[int, int]]:
    """Empty cells 4-connected to any road or town_hall tile where a new tile could be built."""
    tiles = state_view.get("tiles") or []
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    occupied: set[tuple[int, int]] = set()
    road_cells: list[tuple[int, int]] = []
    for t in tiles:
        x, y = int(t.get("x", 0)), int(t.get("y", 0))
        occupied.add((x, y))
        if t.get("type") in ("road", "town_hall"):
            road_cells.append((x, y))
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for rx, ry in road_cells:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = rx + dx, ry + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in occupied and (nx, ny) not in seen:
                seen.add((nx, ny))
                out.append((nx, ny))
    return out


def _hazard_tiles(state_view: dict[str, Any]) -> list[tuple[int, int, str]]:
    """All housing-hazard assets: industrial, coal_plant, gas_peaker, refinery."""
    out: list[tuple[int, int, str]] = []
    for t in state_view.get("tiles") or []:
        tile_type = str(t.get("type", ""))
        if tile_type in _HOUSING_HAZARD_TYPES:
            out.append((int(t.get("x", 0)), int(t.get("y", 0)), tile_type))
    return out


def _min_chebyshev_distance(
    x: int,
    y: int,
    targets: list[tuple[int, int]],
) -> int:
    """Chebyshev distance from (x, y) to the nearest target.  999 if targets is empty."""
    if not targets:
        return 999
    return min(max(abs(x - tx), abs(y - ty)) for tx, ty in targets)


def _has_safe_housing_site(
    state_view: dict[str, Any],
    min_distance: int = _SAFETY_RADIUS,
) -> bool:
    """True if any empty road-adjacent cell is >= min_distance from all hazard tiles.

    A 'safe' housing site keeps residents outside the radius-2 happiness halo
    imposed by industrial, coal, gas, and refinery assets.
    """
    hazards = [(x, y) for x, y, _ in _hazard_tiles(state_view)]
    return any(
        _min_chebyshev_distance(cx, cy, hazards) >= min_distance
        for cx, cy in _empty_road_adjacent_cells(state_view)
    )


def _has_safe_industrial_site(
    state_view: dict[str, Any],
    min_distance: int = _SAFETY_RADIUS,
) -> bool:
    """True if any empty road-adjacent cell is >= min_distance from all houses.

    Industrial creates a happiness halo; placing it near housing reduces resident
    satisfaction.  A safe site keeps that halo away from the existing housing stock.
    """
    houses = [
        (int(t.get("x", 0)), int(t.get("y", 0)))
        for t in (state_view.get("tiles") or [])
        if t.get("type") == "house"
    ]
    return any(
        _min_chebyshev_distance(cx, cy, houses) >= min_distance
        for cx, cy in _empty_road_adjacent_cells(state_view)
    )


def housing_road_expansion_score(state_view: dict[str, Any]) -> float:
    """Score road placements by the quality of housing sites they would unlock.

    For each candidate road cell (empty road-adjacent), inspect cells adjacent
    to it that are not currently build-accessible.  Score the best future housing
    site by its Chebyshev clearance from hazard tiles.  A road that unlocks a
    well-separated future housing site scores higher than one in a cluttered area.
    """
    hazards = [(x, y) for x, y, _ in _hazard_tiles(state_view)]
    road_candidates = _empty_road_adjacent_cells(state_view)
    existing_adjacent: set[tuple[int, int]] = set(road_candidates)
    tiles = state_view.get("tiles") or []
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    occupied: set[tuple[int, int]] = {(int(t.get("x", 0)), int(t.get("y", 0))) for t in tiles}
    best = 0.0
    for rx, ry in road_candidates:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = rx + dx, ry + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if (nx, ny) in occupied or (nx, ny) in existing_adjacent:
                continue
            clearance = _min_chebyshev_distance(nx, ny, hazards)
            if clearance >= _SAFETY_RADIUS:
                best = max(best, (clearance - _SAFETY_RADIUS + 1) * _ROAD_EXPANSION_SCALE)
    return best


def industrial_road_expansion_score(state_view: dict[str, Any]) -> float:
    """Score road placements by the quality of industrial sites they would unlock.

    Mirrors housing_road_expansion_score but measures Chebyshev distance from
    existing houses rather than hazard tiles.  Used to let road outrank industrial
    when all current sites are too close to housing and extending the road network
    would open a better-separated future placement.
    """
    houses = [
        (int(t.get("x", 0)), int(t.get("y", 0)))
        for t in (state_view.get("tiles") or [])
        if t.get("type") == "house"
    ]
    road_candidates = _empty_road_adjacent_cells(state_view)
    existing_adjacent: set[tuple[int, int]] = set(road_candidates)
    tiles = state_view.get("tiles") or []
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    occupied: set[tuple[int, int]] = {(int(t.get("x", 0)), int(t.get("y", 0))) for t in tiles}
    best = 0.0
    for rx, ry in road_candidates:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = rx + dx, ry + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if (nx, ny) in occupied or (nx, ny) in existing_adjacent:
                continue
            clearance = _min_chebyshev_distance(nx, ny, houses)
            if clearance >= _SAFETY_RADIUS:
                best = max(best, (clearance - _SAFETY_RADIUS + 1) * _ROAD_EXPANSION_SCALE)
    return best


def _candidate_road_extensions(state_view: dict[str, Any]) -> list[tuple[int, int]]:
    """Empty tiles adjacent to road/town_hall that would expose at least one new build slot.

    A 'new build slot' is a cell that is not currently accessible (i.e. not already
    in the road/town_hall frontier) — placing a road here expands the frontier.
    Cells that only duplicate existing access are excluded.
    """
    tiles = state_view.get("tiles") or []
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    occupied: set[tuple[int, int]] = set()
    anchors: list[tuple[int, int]] = []
    for t in tiles:
        x, y = int(t.get("x", 0)), int(t.get("y", 0))
        occupied.add((x, y))
        if t.get("type") in ("road", "town_hall"):
            anchors.append((x, y))
    # Current frontier: all empty cells reachable from road or town_hall.
    frontier: set[tuple[int, int]] = set()
    for ax, ay in anchors:
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = ax + dx, ay + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in occupied:
                frontier.add((nx, ny))
    # A candidate is any frontier cell whose road placement exposes ≥1 cell
    # outside the current frontier (genuinely extending the network).
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for rx, ry in frontier:
        if (rx, ry) in seen:
            continue
        seen.add((rx, ry))
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = rx + dx, ry + dy
            if (
                0 <= nx < w
                and 0 <= ny < h
                and (nx, ny) not in occupied
                and (nx, ny) not in frontier
            ):
                out.append((rx, ry))
                break
    return out


def _critical_road_extension_tiles(state_view: dict[str, Any]) -> set[tuple[int, int]]:
    """Subset of _candidate_road_extensions that are strategically important.

    A candidate is critical when any of the following hold:
    - Fewer than 3 candidates remain (scarcity → all are critical).
    - It creates more new build slots than the median candidate (outward expansion).
    - It unlocks a future housing site with Chebyshev clearance >= _SAFETY_RADIUS
      from hazard tiles (safe housing corridor).
    - It unlocks a future industrial site with Chebyshev clearance >= _SAFETY_RADIUS
      from existing houses (safe industrial corridor).
    """
    candidates = _candidate_road_extensions(state_view)
    if not candidates:
        return set()
    if len(candidates) <= 2:
        return set(candidates)

    tiles = state_view.get("tiles") or []
    cfg = state_view.get("config") or {}
    w = int(cfg.get("world_w", 32) or 32)
    h = int(cfg.get("world_h", 32) or 32)
    occupied: set[tuple[int, int]] = {(int(t.get("x", 0)), int(t.get("y", 0))) for t in tiles}
    # Full frontier (road + town_hall adjacent) — used to identify truly NEW slots.
    full_frontier: set[tuple[int, int]] = set()
    for t in tiles:
        if t.get("type") in ("road", "town_hall"):
            tx, ty = int(t.get("x", 0)), int(t.get("y", 0))
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nx, ny = tx + dx, ty + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in occupied:
                    full_frontier.add((nx, ny))

    hazards = [(x, y) for x, y, _ in _hazard_tiles(state_view)]
    houses = [
        (int(t.get("x", 0)), int(t.get("y", 0)))
        for t in tiles
        if t.get("type") == "house"
    ]

    # Per-candidate: count new slots, best housing clearance, best industrial clearance.
    per_candidate: list[tuple[tuple[int, int], int, float, float]] = []
    for rx, ry in candidates:
        new_slots = 0
        best_h = 0.0
        best_i = 0.0
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = rx + dx, ry + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if (nx, ny) in occupied or (nx, ny) in full_frontier:
                continue
            new_slots += 1
            best_h = max(best_h, float(_min_chebyshev_distance(nx, ny, hazards)))
            best_i = max(best_i, float(_min_chebyshev_distance(nx, ny, houses)))
        per_candidate.append(((rx, ry), new_slots, best_h, best_i))

    slot_counts = sorted(d[1] for d in per_candidate)
    median_slots = slot_counts[len(slot_counts) // 2]

    # Housing/industrial clearance criteria only apply when no safe site currently
    # exists.  Without this guard every road candidate is "critical" in hazard-free
    # cities (clearance 999 ≥ 3 everywhere), causing spurious build_crowds_road
    # triggers in open layouts.
    need_safe_housing = not _has_safe_housing_site(state_view)
    need_safe_industrial = not _has_safe_industrial_site(state_view)

    critical: set[tuple[int, int]] = set()
    for (rx, ry), new_slots, best_h, best_i in per_candidate:
        if new_slots > median_slots:
            critical.add((rx, ry))
        if need_safe_housing and best_h >= _SAFETY_RADIUS:
            critical.add((rx, ry))
        if need_safe_industrial and best_i >= _SAFETY_RADIUS:
            critical.add((rx, ry))
    return critical


def _build_would_block_road_network(
    state_view: dict[str, Any],
    build_x: int,
    build_y: int,
) -> bool:
    """True if the proposed build location is a critical road-extension tile."""
    return (build_x, build_y) in _critical_road_extension_tiles(state_view)
