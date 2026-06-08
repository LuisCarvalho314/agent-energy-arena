"""Tests for the stateful LLM supervisor resolver."""

from __future__ import annotations

from agents.llm import ToolCall
from agents.llm_supervisor.actions import SUPERVISOR_ACTION_TOOLS, BuildAction, SurveyAction
from agents.llm_supervisor.memory import SupervisorMemory
from agents.llm_supervisor.policy import build_valid_action_tools, valid_policy_summary
from agents.llm_supervisor.resolver import SupervisorActionResolver
from agents.llm_supervisor.state_summary import summarize_supervisor_state


def _state() -> dict:
    return {
        "day": 0,
        "treasury": 300_000,
        "population": 100,
        "housing_capacity": 100,
        "jobs_total": 60,
        "unemployed": 40,
        "happiness": 1.0,
        "config": {"world_w": 32, "world_h": 32, "active_game_days": 3650},
        "tiles": [
            {
                "id": "town_hall-1",
                "type": "town_hall",
                "x": 16,
                "y": 16,
                "jobs": 30,
                "staffed_jobs": 30,
            },
            {
                "id": "coal_plant-9",
                "type": "coal_plant",
                "x": 8,
                "y": 16,
                "jobs": 30,
                "staffed_jobs": 30,
            },
        ],
        "power_now": {"supply_kw": 375.0, "demand_kw": 50.0},
        "reservoirs_revealed": {"top_k": [], "n_revealed_voxels": 0},
        "wells": [],
        "cumulative_total_served_kwh": 0,
        "cumulative_renewable_served_kwh": 0,
    }


def test_survey_resolver_does_not_repeat_successful_survey_footprints() -> None:
    memory = SupervisorMemory()
    resolver = SupervisorActionResolver(memory)
    state = _state()
    call = ToolCall("survey", {"size": 4})

    first = resolver.from_tool_call(call, state)
    assert isinstance(first, SurveyAction)
    assert (first.x, first.y, first.size) == (16, 16, 4)

    memory.mark_result(first, {"ok": True, "result": {}}, state)
    second = resolver.from_tool_call(call, state)

    assert isinstance(second, SurveyAction)
    assert (second.x, second.y, second.size) != (first.x, first.y, first.size)
    assert memory.summary()["survey_attempts"] == 1
    assert memory.summary()["repeated_survey_candidates_blocked"] >= 1


def test_summary_uses_memory_survey_count_when_api_state_has_none() -> None:
    memory = SupervisorMemory()
    memory.survey_attempts = 3

    summary = summarize_supervisor_state(_state(), None, memory.summary())

    assert "oil phase=surveying surveys=3" in summary
    assert "memory survey_attempts=3" in summary


def test_job_asset_build_is_allowed_when_jobs_are_vacant_but_all_assets_staffed() -> None:
    memory = SupervisorMemory()
    resolver = SupervisorActionResolver(memory)
    state = _state()
    state.update({"jobs_vacant": 8, "employed": 52})

    action = resolver.from_tool_call(ToolCall("build", {"tile_type": "commercial"}), state)

    assert isinstance(action, BuildAction)
    assert action.tile_type == "commercial"
    assert memory.summary()["job_asset_builds_blocked"] == 0


def test_job_asset_build_is_blocked_when_existing_asset_is_underfilled() -> None:
    memory = SupervisorMemory()
    resolver = SupervisorActionResolver(memory)
    state = _state()
    state["tiles"][1]["staffed_jobs"] = 25

    action = resolver.from_tool_call(ToolCall("build", {"tile_type": "commercial"}), state)

    assert action is None
    assert memory.summary()["job_asset_builds_blocked"] == 1
    assert memory.failed_actions[-1].error == "job_asset_blocked_with_underfilled_asset"


def test_non_job_asset_build_is_allowed_when_jobs_are_vacant() -> None:
    memory = SupervisorMemory()
    resolver = SupervisorActionResolver(memory)
    state = _state()
    state.update({"jobs_vacant": 8, "employed": 52})

    action = resolver.from_tool_call(ToolCall("build", {"tile_type": "house"}), state)

    assert isinstance(action, BuildAction)
    assert action.tile_type == "house"
    assert memory.summary()["job_asset_builds_blocked"] == 0


def test_halo_build_resolver_skips_spacing_violation_sites() -> None:
    memory = SupervisorMemory()
    resolver = SupervisorActionResolver(memory)
    state = _state()
    state.update({"population": 92, "jobs_total": 92, "jobs_vacant": 0, "employed": 92})
    state["tiles"].extend(
        [
            {
                "id": "solar_farm-10",
                "type": "solar_farm",
                "x": 15,
                "y": 15,
                "jobs": 2,
                "staffed_jobs": 2,
            },
            {"id": "house-11", "type": "house", "x": 16, "y": 15, "jobs": 0, "staffed_jobs": 0},
            {
                "id": "commercial-12",
                "type": "commercial",
                "x": 17,
                "y": 16,
                "jobs": 12,
                "staffed_jobs": 12,
            },
            {
                "id": "commercial-13",
                "type": "commercial",
                "x": 15,
                "y": 17,
                "jobs": 12,
                "staffed_jobs": 12,
            },
            {
                "id": "solar_farm-14",
                "type": "solar_farm",
                "x": 17,
                "y": 15,
                "jobs": 2,
                "staffed_jobs": 2,
            },
            {
                "id": "solar_farm-15",
                "type": "solar_farm",
                "x": 16,
                "y": 17,
                "jobs": 2,
                "staffed_jobs": 2,
            },
            {
                "id": "solar_farm-16",
                "type": "solar_farm",
                "x": 17,
                "y": 17,
                "jobs": 2,
                "staffed_jobs": 2,
            },
            {"id": "house-17", "type": "house", "x": 14, "y": 15, "jobs": 0, "staffed_jobs": 0},
            {"id": "park-18", "type": "park", "x": 14, "y": 14, "jobs": 0, "staffed_jobs": 0},
        ]
    )

    action = resolver.from_tool_call(ToolCall("build", {"tile_type": "wind_turbine"}), state)

    assert isinstance(action, BuildAction)
    assert action.tile_type == "wind_turbine"
    assert (action.x, action.y) != (15, 14)
    for tile in state["tiles"]:
        if abs(action.x - int(tile["x"])) <= 1 and abs(action.y - int(tile["y"])) <= 1:
            assert tile["type"] in {"road", "battery", "town_hall", "pipeline"}


def test_summary_reports_job_headroom_underfilled_assets_and_build_blocks() -> None:
    memory = SupervisorMemory()
    memory.mark_job_asset_build_blocked("commercial", 5)
    state = _state()
    state.update({"population": 60, "jobs_total": 60, "jobs_vacant": 5, "employed": 55})
    state["tiles"][1]["staffed_jobs"] = 25

    summary = summarize_supervisor_state(state, None, memory.summary())

    assert "job_headroom=0" in summary
    assert "vacant_jobs=5" in summary
    assert "underfilled_job_assets=1" in summary
    assert "job_staffing_gap=5" in summary
    assert "job_asset_build_blocks=1" in summary


def test_dynamic_tools_keep_job_build_types_when_jobs_are_vacant_but_assets_staffed() -> None:
    memory = SupervisorMemory()
    state = _state()
    state.update({"jobs_vacant": 8, "employed": 52})

    tools = build_valid_action_tools(SUPERVISOR_ACTION_TOOLS, state, memory)
    build_tool = next(tool for tool in tools if tool["name"] == "build")
    enum = build_tool["parameters"]["properties"]["tile_type"]["enum"]

    assert "house" in enum
    assert "park" in enum
    assert "battery" in enum
    assert "commercial" in enum
    assert "solar_farm" in enum
    assert "refinery" in enum


def test_dynamic_tools_remove_job_build_types_when_existing_asset_is_underfilled() -> None:
    memory = SupervisorMemory()
    state = _state()
    state["tiles"][1]["staffed_jobs"] = 25

    tools = build_valid_action_tools(SUPERVISOR_ACTION_TOOLS, state, memory)
    build_tool = next(tool for tool in tools if tool["name"] == "build")
    enum = build_tool["parameters"]["properties"]["tile_type"]["enum"]

    assert "house" in enum
    assert "park" in enum
    assert "battery" in enum
    assert "commercial" not in enum
    assert "solar_farm" not in enum
    assert "refinery" not in enum


def test_dynamic_tools_restore_job_build_types_when_no_jobs_are_vacant() -> None:
    memory = SupervisorMemory()
    state = _state()
    state.update({"jobs_vacant": 0, "employed": 60})

    tools = build_valid_action_tools(SUPERVISOR_ACTION_TOOLS, state, memory)
    build_tool = next(tool for tool in tools if tool["name"] == "build")
    enum = build_tool["parameters"]["properties"]["tile_type"]["enum"]

    assert "commercial" in enum
    assert "solar_farm" in enum
    assert "refinery" in enum


def test_summary_reports_valid_intents_and_suppressed_build_types() -> None:
    memory = SupervisorMemory()
    state = _state()
    state["tiles"][1]["staffed_jobs"] = 25

    summary = summarize_supervisor_state(
        state, None, memory.summary(), valid_policy_summary(state, memory)
    )

    assert "valid_intents=" in summary
    assert "build house" in summary
    assert "suppressed_build_types=" in summary
    assert "commercial" in summary
