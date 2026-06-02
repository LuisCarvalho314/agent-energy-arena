"""Recorder ACs (open-source-arena slice 03).

Cover the run-folder allocation contract, schema after one step and many,
metadata field presence, finalize idempotency, reset finalize-and-fresh,
and the action-log-co-tenancy invariant.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from world.action_log import ActionLog
from world.api import create_app
from world.recorder import Recorder, _unique_run_id
from world.scenario import Scenario
from world.sim import World


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_runs_root_none_allocates_no_recorder() -> None:
    """Tests that don't opt in keep the filesystem clean."""
    world = World()
    assert world.recorder is None


def test_recorder_construction_does_not_touch_filesystem(tmp_path: Path) -> None:
    """Filesystem allocation is lazy: a never-stepped recorder leaves
    no trace under `runs/`. This is what keeps `uvicorn` boots and
    `create_app(world=...)` test helpers from littering `runs/`."""
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    assert not world.recorder.dir.exists()
    assert not world.recorder.metadata_path.exists()


def test_recorder_materializes_on_first_step(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    world.step(days=1)
    assert world.recorder.dir.exists()
    assert (world.recorder.dir / "metadata.json").exists()


def test_metadata_fields_present(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    world.step(days=1)  # trigger materialization
    payload = json.loads(world.recorder.metadata_path.read_text())
    assert payload["run_id"] == world.recorder.run_id
    assert payload["seed"] == world.state.seed
    assert payload["scenario"] is None  # NullScenario default
    assert payload["session"] == "agent"
    assert isinstance(payload["started_at"], float)


def test_metadata_captures_attached_scenario(tmp_path: Path) -> None:
    class MyScenario(Scenario):
        pass

    world = World(runs_root=str(tmp_path), scenario=MyScenario())
    assert world.recorder is not None
    world.step(days=1)
    payload = json.loads(world.recorder.metadata_path.read_text())
    assert payload["scenario"] is not None
    assert payload["scenario"].endswith(".MyScenario")


def test_states_jsonl_line_count_matches_steps(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None

    # No steps yet → file may not exist (or be empty).
    states_path = world.recorder.states_path
    assert not states_path.exists() or states_path.read_text() == ""

    world.step(days=3)
    entries = _read_jsonl(states_path)
    assert len(entries) == 3
    # Days are 0-indexed at the recorder boundary (pre-increment).
    assert [e["day"] for e in entries] == [0, 1, 2]


def test_states_jsonl_after_many_steps(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    world.step(days=7)
    world.step(days=7)
    entries = _read_jsonl(world.recorder.states_path)
    assert len(entries) == 14
    # Each entry carries an embedded state snapshot and per-day summary.
    sample = entries[-1]
    assert set(sample.keys()) == {"day", "state", "summary"}
    state = sample["state"]
    summary = sample["summary"]
    assert isinstance(state, dict)
    assert isinstance(summary, dict)
    assert "treasury" in state
    assert "tiles" in state
    assert "blackout_hours" in summary


def test_finalize_writes_final_json_once(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    world.step(days=1)
    final_path = world.recorder.final_path
    assert not final_path.exists()

    world.recorder.finalize(world)
    assert final_path.exists()
    first_payload = final_path.read_text()

    # Mutate state, finalize again — file is unchanged (idempotent).
    world.state.treasury = -99999.0
    world.recorder.finalize(world)
    assert final_path.read_text() == first_payload

    payload = json.loads(first_payload)
    assert payload["run_id"] == world.recorder.run_id
    assert "final_state" in payload
    assert isinstance(payload["ended_at"], float)


def test_reset_finalizes_current_and_allocates_fresh(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    prev_recorder = world.recorder
    prev_dir = prev_recorder.dir

    world.step(days=2)
    world.reset(seed=7)
    new_recorder = world.recorder
    assert new_recorder is not None
    assert new_recorder is not prev_recorder
    assert new_recorder.run_id != prev_recorder.run_id

    # Prior run preserved — folder still exists and final.json was
    # written by the reset hand-off.
    assert prev_dir.exists()
    assert (prev_dir / "final.json").exists()
    # New run's metadata reflects the new seed (after the first step
    # materializes its folder).
    world.step(days=1)
    new_meta = json.loads(new_recorder.metadata_path.read_text())
    assert new_meta["seed"] == 7


def test_reset_without_step_leaves_no_trace(tmp_path: Path) -> None:
    """A recorder that never recorded a state is invisible on disk —
    the per-reset folder churn from `uvicorn` boots that the user
    never plays is what we're guarding against."""
    world = World(runs_root=str(tmp_path))
    assert world.recorder is not None
    prev_dir = world.recorder.dir

    world.reset(seed=7)  # finalize a recorder that never stepped

    assert not prev_dir.exists()
    # Sibling listing: only the new recorder's path placeholder, also
    # un-materialized.
    materialized = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert materialized == []


def test_action_log_lives_in_same_run_folder(tmp_path: Path) -> None:
    """Default `create_app()` co-locates actions.jsonl with the recorder."""
    app = create_app(runs_root=str(tmp_path))
    client = TestClient(app)
    client.post("/reset", json={"seed": 11})
    client.post("/step", json={"days": 1})

    world = app.state.world
    log = app.state.action_log
    # The /reset call replaced the recorder, so the live recorder's
    # folder is the one the latest actions land in.
    assert log.dir == world.recorder.dir
    # Recorder + log artifacts share the directory.
    assert (world.recorder.dir / "metadata.json").exists()
    assert (world.recorder.dir / "actions.jsonl").exists()
    assert (world.recorder.dir / "states.jsonl").exists()


def test_recorder_direct_construction_writes_metadata_on_first_step(
    tmp_path: Path,
) -> None:
    """Recorder works standalone; metadata is written on first
    materialization (record_step). Construction alone touches no disk."""
    rec = Recorder(
        root=str(tmp_path),
        seed=99,
        scenario_name="scenarios.foo",
        session="ui",
    )
    assert not rec.dir.exists()
    # Force materialization via the same path record_step takes.
    rec._materialize()
    payload = json.loads(rec.metadata_path.read_text())
    assert payload["seed"] == 99
    assert payload["scenario"] == "scenarios.foo"
    assert payload["session"] == "ui"


def test_session_marker_propagates_to_metadata(tmp_path: Path) -> None:
    world = World(runs_root=str(tmp_path), session="ui")
    assert world.recorder is not None
    world.step(days=1)
    payload = json.loads(world.recorder.metadata_path.read_text())
    assert payload["session"] == "ui"


def test_run_id_uses_prefix_and_timestamp(tmp_path: Path) -> None:
    """Run folders are named `<prefix>-<YYYYMMDD-HHMMSS>` — readable at a
    glance, with the origin prefix carried from the entry point ("eval"
    for evaluate.py, "play" for the UI server)."""
    world = World(runs_root=str(tmp_path), run_prefix="eval")
    assert world.recorder is not None
    assert re.fullmatch(r"eval-\d{8}-\d{6}", world.recorder.run_id)


def test_unique_run_id_suffixes_on_same_second_collision(tmp_path: Path) -> None:
    """A run reset within the same wall-clock second can't reuse the prior
    (preserved) folder — `_unique_run_id` takes the next free suffix."""
    base = "eval-20260601-120000"
    assert _unique_run_id(tmp_path, base) == base  # no collision → unchanged
    (tmp_path / base).mkdir()
    assert _unique_run_id(tmp_path, base) == f"{base}-2"
    (tmp_path / f"{base}-2").mkdir()
    assert _unique_run_id(tmp_path, base) == f"{base}-3"


def test_action_log_provided_takes_precedence_over_default(tmp_path: Path) -> None:
    """If the caller passes an action_log, create_app respects it."""
    explicit_log = ActionLog(root=tmp_path / "elsewhere")
    app = create_app(action_log=explicit_log, runs_root=str(tmp_path / "runs"))
    client = TestClient(app)
    client.post("/step", json={"days": 1})
    # Action log stayed where the caller put it.
    assert (tmp_path / "elsewhere" / explicit_log.run_id / "actions.jsonl").exists()
    # Recorder still wrote to its own folder.
    assert app.state.world.recorder is not None
    assert (app.state.world.recorder.dir / "metadata.json").exists()
