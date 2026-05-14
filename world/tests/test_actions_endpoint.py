"""`GET /actions` slicing — fixture-driven.

The slicing algorithm is mirrored verbatim in `world/ui/app.js` for replay
mode. The fixture file in `fixtures/actions_slicing.jsonl` is the shared
ground truth; the JS port consumes the same file when replaying a recorded
run, so divergence would surface as a UI mismatch on real runs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from world.action_log import ActionLog
from world.api import _slice_actions_for_day, create_app
from world.sim import World

FIXTURE = Path(__file__).parent / "fixtures" / "actions_slicing.jsonl"


def _entries() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_slice_initial_reset_emits_its_own_slice() -> None:
    s = _slice_actions_for_day(_entries(), 0)
    # Latest day=0 slice is the in-flight tail after the second /reset.
    assert s["day_start"] == 0
    assert s["day_end"] == 0
    assert [e["endpoint"] for e in s["entries"]] == ["/build"]
    assert s["entries"][0]["params"]["tile_type"] == "battery"


def test_slice_multi_day_step_spans_range() -> None:
    s = _slice_actions_for_day(_entries(), 5)
    assert s["day_start"] == 1
    assert s["day_end"] == 7
    # Any day in [1, 7] returns the same slice.
    assert _slice_actions_for_day(_entries(), 1) == s
    assert _slice_actions_for_day(_entries(), 7) == s
    endpoints = [e["endpoint"] for e in s["entries"]]
    assert endpoints == ["/build", "/step"]


def test_failed_step_does_not_terminate_and_is_filtered() -> None:
    s = _slice_actions_for_day(_entries(), 8)
    endpoints = [e["endpoint"] for e in s["entries"]]
    # Failed /step is dropped entirely (widget never surfaces failures),
    # and the slice still runs to the next successful terminator (/reset).
    assert endpoints == ["/control/well", "/reset"]
    assert all(e["ok"] for e in s["entries"])


def test_unknown_day_returns_empty_slice() -> None:
    s = _slice_actions_for_day(_entries(), 99)
    assert s == {"day_start": 99, "day_end": 99, "entries": []}


def test_endpoint_returns_in_flight_slice(tmp_path: Path) -> None:
    """End-to-end: copy the fixture into a fresh ActionLog dir and confirm
    the FastAPI route returns the same slice the helper does."""
    runs_root = tmp_path / "runs"
    log = ActionLog(root=runs_root)
    shutil.copy(FIXTURE, log.path)
    app = create_app(world=World(), action_log=log)
    client = TestClient(app)
    r = client.get("/actions", params={"day": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["day_start"] == 0
    assert body["day_end"] == 0
    assert [e["endpoint"] for e in body["entries"]] == ["/build"]


def test_endpoint_empty_log_returns_empty_slice(tmp_path: Path) -> None:
    """Fresh world, no actions yet — endpoint returns an empty slice at the
    requested day rather than 404. The UI polls every tick; an empty slice
    is the steady state right after /reset."""
    log = ActionLog(root=tmp_path / "runs")
    app = create_app(world=World(), action_log=log)
    client = TestClient(app)
    # The ActionLog constructor already created the file; ensure it's empty.
    log.path.write_text("")
    r = client.get("/actions", params={"day": 0})
    assert r.status_code == 200
    assert r.json() == {"day_start": 0, "day_end": 0, "entries": []}
