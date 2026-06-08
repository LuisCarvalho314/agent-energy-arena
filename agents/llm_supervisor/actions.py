"""Deterministic action objects for the LLM supervisor.

The LLM layer emits provider-normalized ``ToolCall`` values. This module
turns those untrusted argument dicts into small, typed action objects
whose only job is to execute the matching ``ApiClient`` call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agents.api_client import ApiClient
from agents.llm import ToolCall
from agents.prompts import TILE_TYPES
from world.catalog import TILE_CATALOG
from world.placement import HALO_ADMITTED_NEIGHBORS, HALO_TYPES

# Drilling quality gates (mirrors scripted agent thresholds).
DRILL_OIL_THRESHOLD_BBL: float = 5_000.0
DRILL_PERM_THRESHOLD_MD: float = 200.0

# Carbon price above which demolish prefers coal over proximity.
COAL_DEMOLISH_CARBON_USD: float = 80.0

# Minimum Chebyshev distance between injection and producer targets.
INJECTION_CHEBYSHEV_MIN: int = 2

# Power plants that belong on the perimeter, away from the road cluster.
_PERIMETER_PLANT_TYPES: frozenset[str] = frozenset(
    {"solar_farm", "wind_turbine", "gas_peaker", "battery"}
)


class Action(Protocol):
    """A deterministic world mutation backed by the public API client."""

    name: str

    def execute(self, api: ApiClient) -> dict[str, Any]:
        """Execute the action through ``api`` and return its envelope."""


@dataclass(frozen=True)
class BuildAction:
    tile_type: str
    x: int
    y: int
    name: str = "build"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.build(tile_type=self.tile_type, x=self.x, y=self.y)


@dataclass(frozen=True)
class DemolishAction:
    x: int
    y: int
    name: str = "demolish"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.demolish(x=self.x, y=self.y)


@dataclass(frozen=True)
class SurveyAction:
    x: int
    y: int
    size: int = 8
    name: str = "survey"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.survey(x=self.x, y=self.y, size=self.size)


@dataclass(frozen=True)
class DrillAction:
    x: int
    y: int
    target_z: int
    well_type: str = "production"
    name: str = "drill"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.drill(
            x=self.x,
            y=self.y,
            target_z=self.target_z,
            well_type=self.well_type,
        )


@dataclass(frozen=True)
class SetWellRateAction:
    well_id: str
    rate_bbl_day: float
    name: str = "set_well_rate"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.control_well(well_id=self.well_id, rate_bbl_day=self.rate_bbl_day)


@dataclass(frozen=True)
class SetRefineryRateAction:
    refinery_id: str
    rate_bbl_day: float
    name: str = "set_refinery_rate"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        return api.control_refinery(
            refinery_id=self.refinery_id,
            rate_bbl_day=self.rate_bbl_day,
        )


@dataclass(frozen=True)
class GasPeakerWithPipelineAction:
    """Builds a gas_peaker then lays an L-path pipeline to the nearest refinery.

    Gas peakers only dispatch when sharing a 4-connected pipeline network with
    an operational refinery.  The pipeline path is precomputed from state at
    action-construction time; individual segment failures (occupied cell,
    insufficient funds) are swallowed so a partial path still benefits the
    agent.  Returns the gas_peaker build envelope as the primary result.
    """

    x: int
    y: int
    pipeline_path: tuple[tuple[int, int], ...]
    name: str = "build"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        result = api.build(tile_type="gas_peaker", x=self.x, y=self.y)
        if result.get("ok"):
            for px, py in self.pipeline_path:
                try:
                    api.build(tile_type="pipeline", x=px, y=py)
                except RuntimeError:
                    pass
        return result


@dataclass(frozen=True)
class PairedBuildAction:
    """Builds a park at (park_x, park_y) then the primary tile at (x, y).

    Used to couple every house placement with a nearby park. The park is
    placed first so happiness bonuses are already in effect by the time
    the house lands. The primary tile's API result is returned as the
    action envelope so the caller's success/failure logic is unchanged.
    Park failures (occupied cell, insufficient funds) are silently
    swallowed — the house build still proceeds.
    """

    tile_type: str
    x: int
    y: int
    park_x: int
    park_y: int
    name: str = "build"

    def execute(self, api: ApiClient) -> dict[str, Any]:
        try:
            api.build(tile_type="park", x=self.park_x, y=self.park_y)
        except RuntimeError:
            pass
        return api.build(tile_type=self.tile_type, x=self.x, y=self.y)


SUPERVISOR_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "build",
        "description": "Request building this tile type; supervisor chooses location.",
        "parameters": {
            "type": "object",
            "properties": {"tile_type": {"type": "string", "enum": TILE_TYPES}},
            "required": ["tile_type"],
        },
    },
    {
        "name": "demolish",
        "description": "Request deterministic demolition; optional tile_type narrows target.",
        "parameters": {
            "type": "object",
            "properties": {"tile_type": {"type": "string", "enum": TILE_TYPES}},
        },
    },
    {
        "name": "survey",
        "description": "Request next deterministic survey sweep; size defaults to 4.",
        "parameters": {
            "type": "object",
            "properties": {"size": {"type": "integer", "minimum": 4, "maximum": 16}},
        },
    },
    {
        "name": "drill",
        "description": "Request deterministic best revealed drill target.",
        "parameters": {
            "type": "object",
            "properties": {"well_type": {"type": "string", "enum": ["production", "injection"]}},
        },
    },
    {
        "name": "set_well_rate",
        "description": "Set a well's setpoint rate in bbl/day.",
        "parameters": {
            "type": "object",
            "properties": {
                "well_id": {"type": "string"},
                "rate_bbl_day": {"type": "number", "minimum": 0},
            },
            "required": ["well_id", "rate_bbl_day"],
        },
    },
    {
        "name": "set_refinery_rate",
        "description": "Set a refinery's throughput in bbl/day of crude input.",
        "parameters": {
            "type": "object",
            "properties": {
                "refinery_id": {"type": "string"},
                "rate_bbl_day": {"type": "number", "minimum": 0},
            },
            "required": ["refinery_id", "rate_bbl_day"],
        },
    },
    {
        "name": "step",
        "description": "Advance the simulation by days days. Must be the last tool call.",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 7}},
            "required": ["days"],
        },
    },
]


ActionBuilder = Callable[[dict[str, Any], dict[str, Any] | None], Action]


def _build_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    tile_type = str(args["tile_type"])
    sv = _require_state(state_view)

    # # Day-0 bootstrap: place a coal plant adjacent to the existing starter coal plant.
    # day = int(sv.get("day", 0) or 0)
    # if day == 0:
    #     x, y = _pick_coal_adjacent_xy(sv)
    #     return BuildAction(tile_type="coal_plant", x=x, y=y)

    if tile_type == "gas_peaker":
        x, y = _pick_build_xy(tile_type, sv)
        refineries = [t for t in sv.get("tiles") or [] if t.get("type") == "refinery"]
        if refineries:
            refineries.sort(key=lambda t: abs(int(t["x"]) - x) + abs(int(t["y"]) - y))
            rx, ry = int(refineries[0]["x"]), int(refineries[0]["y"])
            w, h = _config(sv)
            path = tuple(
                (px, py) for px, py in _l_path(x, y, rx, ry) if 0 <= px < w and 0 <= py < h
            )
            return GasPeakerWithPipelineAction(x=x, y=y, pipeline_path=path)
        return BuildAction(tile_type=tile_type, x=x, y=y)

    if tile_type == "house":
        cx, cy = _town_hall_xy(sv)
        # First-ever house: ensure a park exists near the town hall first.
        if not _has_park_near(cx, cy, sv, radius=1):
            park_xy = _pick_park_xy_near(cx, cy, sv, max_radius=1)
            if park_xy is not None:
                return BuildAction(tile_type="park", x=park_xy[0], y=park_xy[1])
        # Pair the house with a park within radius 2 (closer is better).
        x, y = _pick_build_xy(tile_type, sv)
        if not _has_park_near(x, y, sv, radius=1):
            park_xy = _pick_park_xy_near(x, y, sv, max_radius=1)
            if park_xy is not None:
                return PairedBuildAction(
                    tile_type=tile_type, x=x, y=y, park_x=park_xy[0], park_y=park_xy[1]
                )
        return BuildAction(tile_type=tile_type, x=x, y=y)

    x, y = _pick_build_xy(tile_type, sv)
    return BuildAction(tile_type=tile_type, x=x, y=y)


def _demolish_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    return DemolishAction(*_pick_demolish_xy(args.get("tile_type"), _require_state(state_view)))


def _survey_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    sv = _require_state(state_view)
    size = int(args.get("size", 4))
    x, y = _pick_survey_xy(sv, size=size)
    return SurveyAction(x=x, y=y, size=size)


def _drill_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    well_type = str(args.get("well_type", "production"))
    sv = _require_state(state_view)
    if well_type == "injection":
        x, y, target_z = _pick_injection_target(sv)
    else:
        x, y, target_z = _pick_drill_target(sv)
    return DrillAction(x=x, y=y, target_z=target_z, well_type=well_type)


def _set_well_rate_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    return SetWellRateAction(
        well_id=str(args["well_id"]),
        rate_bbl_day=float(args["rate_bbl_day"]),
    )


def _set_refinery_rate_action(args: dict[str, Any], state_view: dict[str, Any] | None) -> Action:
    return SetRefineryRateAction(
        refinery_id=str(args["refinery_id"]),
        rate_bbl_day=float(args["rate_bbl_day"]),
    )


ACTION_BUILDERS: dict[str, ActionBuilder] = {
    "build": _build_action,
    "demolish": _demolish_action,
    "survey": _survey_action,
    "drill": _drill_action,
    "set_well_rate": _set_well_rate_action,
    "set_refinery_rate": _set_refinery_rate_action,
}


def action_from_tool_call(
    call: ToolCall, state_view: dict[str, Any] | None = None
) -> Action | None:
    """Convert a normalized LLM ``ToolCall`` into an executable action.

    Unknown tool names return ``None`` so hallucinated calls can be
    skipped. Known tool names keep the existing strict behavior: missing
    or malformed arguments raise ``KeyError``, ``TypeError``, or
    ``ValueError`` before any API call is made.
    """
    builder = ACTION_BUILDERS.get(call.name)
    if builder is None:
        return None
    return builder(call.arguments, state_view)


def execute_tool_call(
    api: ApiClient,
    call: ToolCall,
    state_view: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Compatibility helper: parse a tool call and execute its action."""
    action = action_from_tool_call(call, state_view)
    if action is None:
        return None
    return action.execute(api)


def _require_state(state_view: dict[str, Any] | None) -> dict[str, Any]:
    if state_view is None:
        raise ValueError("state_view is required when tool call omits coordinates")
    return state_view


def _config(state_view: dict[str, Any]) -> tuple[int, int]:
    cfg = state_view.get("config") or {}
    return int(cfg.get("world_w", 32)), int(cfg.get("world_h", 32))


def _occupied(state_view: dict[str, Any]) -> set[tuple[int, int]]:
    return {(int(t["x"]), int(t["y"])) for t in state_view.get("tiles") or []}


def _town_hall_xy(state_view: dict[str, Any]) -> tuple[int, int]:
    w, h = _config(state_view)
    for tile in state_view.get("tiles") or []:
        if tile.get("type") == "town_hall":
            return int(tile["x"]), int(tile["y"])
    return w // 2, h // 2


def _spiral(cx: int, cy: int, w: int, h: int):
    yield cx, cy
    max_radius = max(w, h)
    for radius in range(1, max_radius + 1):
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if max(abs(x - cx), abs(y - cy)) != radius:
                    continue
                if 0 <= x < w and 0 <= y < h:
                    yield x, y


def _l_path(
    ax: int, ay: int, bx: int, by: int
) -> list[tuple[int, int]]:
    """L-shaped 4-connected walk from (ax,ay) exclusive to (bx,by) exclusive.

    Walks x-first along ay, then y-first along bx.  Neither endpoint is
    included — the caller occupies those cells (well/refinery).
    """
    out: list[tuple[int, int]] = []
    if ax != bx:
        sx = 1 if bx > ax else -1
        x = ax + sx
        while True:
            if (x, ay) == (bx, by):
                break
            out.append((x, ay))
            if x == bx:
                break
            x += sx
    if ay != by:
        sy = 1 if by > ay else -1
        y = ay + sy
        while True:
            if (bx, y) == (bx, by):
                break
            if (bx, y) != (ax, ay):
                out.append((bx, y))
            if y == by:
                break
            y += sy
    return out


def _perimeter_spiral(cx: int, cy: int, w: int, h: int):
    """Expanding Chebyshev rings starting at radius 4 — keeps power plants
    away from the civilian road cluster near the town hall."""
    for radius in range(4, max(w, h) + 1):
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if max(abs(x - cx), abs(y - cy)) != radius:
                    continue
                if 0 <= x < w and 0 <= y < h:
                    yield x, y


def _road_set(state_view: dict[str, Any]) -> set[tuple[int, int]]:
    return {
        (int(t["x"]), int(t["y"]))
        for t in state_view.get("tiles") or []
        if t.get("type") in {"road", "town_hall"}
    }


def _road_adjacent(x: int, y: int, roads: set[tuple[int, int]]) -> bool:
    return any((x + dx, y + dy) in roads for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def _pick_coal_adjacent_xy(state_view: dict[str, Any]) -> tuple[int, int]:
    """Road-adjacent empty cell nearest to the existing coal plant.

    Coal requires road adjacency, so we search outward from the first
    coal tile we find. Falls back to the normal road-adjacent spiral from
    town hall if no existing coal plant is present.
    """
    w, h = _config(state_view)
    occupied = _occupied(state_view)
    roads = _road_set(state_view)
    coal = next(
        (t for t in state_view.get("tiles") or [] if t.get("type") == "coal_plant"),
        None,
    )
    if coal is not None:
        cx, cy = int(coal["x"]), int(coal["y"])
        for x, y in _spiral(cx, cy, w, h):
            if (x, y) in occupied:
                continue
            if not _road_adjacent(x, y, roads):
                continue
            if not _spacing_allowed("coal_plant", x, y, state_view):
                continue
            return x, y
    return _pick_build_xy("coal_plant", state_view)


def _pick_build_xy(tile_type: str, state_view: dict[str, Any]) -> tuple[int, int]:
    if tile_type in _PERIMETER_PLANT_TYPES:
        return _pick_perimeter_xy(tile_type, state_view)
    w, h = _config(state_view)
    cx, cy = _town_hall_xy(state_view)
    occupied = _occupied(state_view)
    roads = _road_set(state_view)
    spec = TILE_CATALOG.get(tile_type)
    requires_road = bool(spec and spec.requires_road)

    for x, y in _spiral(cx, cy, w, h):
        if (x, y) in occupied:
            continue
        if tile_type == "road":
            if _road_adjacent(x, y, roads):
                return x, y
            continue
        if requires_road and not _road_adjacent(x, y, roads):
            continue
        if not _spacing_allowed(tile_type, x, y, state_view):
            continue
        return x, y
    raise ValueError(f"no deterministic build site for {tile_type}")


def _pick_perimeter_xy(tile_type: str, state_view: dict[str, Any]) -> tuple[int, int]:
    """Place a power plant far from the town-hall cluster (perimeter-first spiral)."""
    w, h = _config(state_view)
    cx, cy = _town_hall_xy(state_view)
    occupied = _occupied(state_view)
    for x, y in _perimeter_spiral(cx, cy, w, h):
        if (x, y) in occupied:
            continue
        if not _spacing_allowed(tile_type, x, y, state_view):
            continue
        return x, y
    raise ValueError(f"no deterministic perimeter site for {tile_type}")


def _spacing_allowed(tile_type: str, x: int, y: int, state_view: dict[str, Any]) -> bool:
    if tile_type not in HALO_TYPES:
        return True
    tiles_by_xy = {
        (int(t["x"]), int(t["y"])): str(t.get("type", "")) for t in state_view.get("tiles") or []
    }
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            neighbor_type = tiles_by_xy.get((x + dx, y + dy))
            if neighbor_type is None:
                continue
            if neighbor_type in HALO_ADMITTED_NEIGHBORS:
                continue
            return False
    return True


def _pick_demolish_xy(tile_type: Any, state_view: dict[str, Any]) -> tuple[int, int]:
    cx, cy = _town_hall_xy(state_view)
    candidates = [
        t
        for t in state_view.get("tiles") or []
        if not _is_demolish_protected(t) and (tile_type is None or t.get("type") == str(tile_type))
    ]
    # When carbon price exceeds the threshold and no specific type was requested,
    # prefer coal plants — they carry the largest carbon liability per tile.
    if tile_type is None:
        carbon_price = float((state_view.get("config") or {}).get("carbon_price", 0.0))
        coal = [t for t in candidates if t.get("type") == "coal_plant"]
        if carbon_price >= COAL_DEMOLISH_CARBON_USD and coal:
            candidates = coal
    candidates.sort(
        key=lambda t: (
            abs(int(t["x"]) - cx) + abs(int(t["y"]) - cy),
            str(t.get("id", "")),
        )
    )
    if not candidates:
        raise ValueError("no deterministic demolish target")
    target = candidates[0]
    return int(target["x"]), int(target["y"])


def _is_demolish_protected(tile: dict[str, Any]) -> bool:
    """Protect free starter infrastructure and parks from supervisor demolition.

    Town hall, starter roads, and starter coal are all seeded at reset
    with ``capex_paid=0``. Parks are always protected — they are sited to
    satisfy the happiness radius requirement for adjacent housing and
    removing one degrades population growth.
    """
    if tile.get("type") in {"town_hall", "park", "coal_plant"}:
        return True
    return float(tile.get("capex_paid", 0) or 0) <= 0


def _has_park_near(x: int, y: int, state_view: dict[str, Any], *, radius: int = 2) -> bool:
    """Return True if any park tile is within Chebyshev distance ``radius``."""
    for tile in state_view.get("tiles") or []:
        if tile.get("type") != "park":
            continue
        if max(abs(int(tile["x"]) - x), abs(int(tile["y"]) - y)) <= radius:
            return True
    return False


def _pick_park_xy_near(
    x: int,
    y: int,
    state_view: dict[str, Any],
    *,
    max_radius: int = 2,
) -> tuple[int, int] | None:
    """Nearest unoccupied in-bounds cell within Chebyshev ``max_radius``.

    Searches ring-by-ring (radius 1, then 2, …) so closer placements are
    always preferred. Parks have no road requirement.
    """
    w, h = _config(state_view)
    occupied = _occupied(state_view)
    for radius in range(1, max_radius + 1):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                px, py = x + dx, y + dy
                if not (0 <= px < w and 0 <= py < h):
                    continue
                if (px, py) not in occupied:
                    return px, py
    return None


def _pick_survey_xy(state_view: dict[str, Any], *, size: int) -> tuple[int, int]:
    w, h = _config(state_view)
    cx, cy = _town_hall_xy(state_view)
    top = (state_view.get("reservoirs_revealed") or {}).get("top_k") or []
    idx = len(top) % 21
    offsets = (
        (0, 0),
        (-12, -12),
        (12, -12),
        (-12, 12),
        (12, 12),
        (-12, 0),
        (12, 0),
        (0, -12),
        (0, 12),
        (-6, -6),
        (6, -6),
        (-6, 6),
        (6, 6),
        (-12, -6),
        (12, -6),
        (-12, 6),
        (12, 6),
        (-6, -12),
        (6, -12),
        (-6, 12),
        (6, 12),
    )
    margin = max(0, size // 2)
    dx, dy = offsets[idx]
    return max(margin, min(w - margin - 1, cx + dx)), max(margin, min(h - margin - 1, cy + dy))


def _pick_drill_target(state_view: dict[str, Any]) -> tuple[int, int, int]:
    occupied = _occupied(state_view)
    top = (state_view.get("reservoirs_revealed") or {}).get("top_k") or []
    if not top:
        raise ValueError("no revealed reservoir target for deterministic drill")
    # Quality-gated fresh drill: unoccupied surface, oil and perm above thresholds.
    for voxel in top:
        oil = float(voxel.get("oil_estimate_bbl", 0))
        perm = float(voxel.get("perm_estimate_md", 0))
        if oil < DRILL_OIL_THRESHOLD_BBL or perm < DRILL_PERM_THRESHOLD_MD:
            continue
        x, y, z = int(voxel["x"]), int(voxel["y"]), int(voxel["z"])
        if (x, y) not in occupied:
            return x, y, z
    # Stacked-completion fallback: second producer under an existing one.
    stacked = _pick_stacked_drill_target(state_view, top)
    if stacked is not None:
        return stacked
    raise ValueError("no quality-passing or stacked deterministic drill target")


def _pick_stacked_drill_target(
    state_view: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[int, int, int] | None:
    """Second producer at the same surface tile as an existing one.

    Per reservoir-scale-and-stacked-completions §4.12: same (x, y) as an
    existing producer, same reservoir_id, |Δz| ≥ 3.  Fires at most once
    per producer (detected by >1 well at the same (x, y)).  Oil threshold
    still applies; perm gate is dropped — the sunk-cost surface tile makes
    even tight rock commercial.
    """
    wells = state_view.get("wells") or []
    producers = [w for w in wells if w.get("type") == "production"]
    if not producers:
        return None
    wells_at_xy: dict[tuple[int, int], int] = {}
    for w in wells:
        xy = (int(w["x"]), int(w["y"]))
        wells_at_xy[xy] = wells_at_xy.get(xy, 0) + 1
    for prod in sorted(producers, key=lambda p: str(p.get("id", ""))):
        px, py = int(prod["x"]), int(prod["y"])
        if wells_at_xy.get((px, py), 0) > 1:
            continue  # already stacked
        prod_rid = prod.get("reservoir_id")
        if prod_rid is None:
            continue
        prod_z = int(prod["target_z"])
        for v in candidates:
            if int(v["x"]) != px or int(v["y"]) != py:
                continue
            if v.get("reservoir_id") != prod_rid:
                continue
            vz = int(v["z"])
            if abs(vz - prod_z) < 3:
                continue
            if float(v.get("oil_estimate_bbl", 0)) < DRILL_OIL_THRESHOLD_BBL:
                continue
            return px, py, vz
    return None


def _pick_injection_target(state_view: dict[str, Any]) -> tuple[int, int, int]:
    """Injection well sited in the same reservoir as an existing producer.

    Chebyshev distance ≥ INJECTION_CHEBYSHEV_MIN ensures the injector
    qualifies for the producer's pressure_boost without triggering early
    breakthrough.  Falls back to the best unoccupied revealed voxel when
    no reservoir-paired candidate exists.
    """
    w, h = _config(state_view)
    occupied = _occupied(state_view)
    wells = state_view.get("wells") or []
    candidates = (state_view.get("reservoirs_revealed") or {}).get("top_k") or []
    producers = [w_ for w_ in wells if w_.get("type") == "production"]
    for prod in sorted(producers, key=lambda p: str(p.get("id", ""))):
        prod_rid = prod.get("reservoir_id")
        if prod_rid is None:
            continue
        prod_z = int(prod.get("target_z", 0))
        for v in candidates:
            x, y, z = int(v["x"]), int(v["y"]), int(v["z"])
            if v.get("reservoir_id") != prod_rid:
                continue
            if (x, y) in occupied or not (0 <= x < w and 0 <= y < h):
                continue
            cheb = max(abs(x - int(prod["x"])), abs(y - int(prod["y"])), abs(z - prod_z))
            if cheb < INJECTION_CHEBYSHEV_MIN:
                continue
            return x, y, z
    # Fallback: best unoccupied revealed voxel.
    for voxel in candidates:
        x, y, z = int(voxel["x"]), int(voxel["y"]), int(voxel["z"])
        if (x, y) not in occupied and 0 <= x < w and 0 <= y < h:
            return x, y, z
    raise ValueError("no deterministic injection target")
