"""Per-run recorder. Writes metadata, per-day state log, and final snapshot.

The recorder owns a run folder under `runs/` (peer of `action_log.py`'s
`actions.jsonl`). It is allocated by `World` at construction time and is
finalized + replaced on `World.reset` — no recorded run is destroyed by
a reset.

Filesystem allocation is *lazy*: `__init__` only computes paths and
stashes the metadata payload. The `runs/<run_id>/` directory and
`metadata.json` are written on the first `record_step` call. A
recorder that's constructed and never has a state recorded leaves no
trace on disk — this keeps every `uvicorn` boot and `World()`
construction in tests from littering the real `runs/` directory.
`finalize` on an un-materialized recorder is a no-op for the same
reason: a run with zero recorded days isn't a "run" worth marking.

Three artifacts per (materialized) run folder:
  * `metadata.json` — seed, scenario dotted path, session marker,
    started-at timestamp, run id. Written when the first day is
    recorded (or on `finalize` if a state has already been recorded).
  * `states.jsonl` — one line per simulated day. `record_step(world, day)`
    appends an entry with the end-of-day `state_dict()` and the
    per-day `today_summary_so_far`. Scenario-driven weather overrides
    and `scenario_trace` entries are visible through the embedded
    state.
  * `final.json` — written exactly once by `finalize(world)`. Repeated
    finalize calls after the first are no-ops.

The recorder is purely additive — `world.action_log.ActionLog`
continues to own `actions.jsonl` inside the same folder.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from world.sim import World


class Recorder:
    def __init__(
        self,
        root: str | os.PathLike[str] = "runs",
        run_id: str | None = None,
        *,
        seed: int,
        scenario_name: str | None,
        session: str,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id or _new_run_id()
        self.dir = self.root / self.run_id
        self.metadata_path = self.dir / "metadata.json"
        self.states_path = self.dir / "states.jsonl"
        self.final_path = self.dir / "final.json"
        self._finalized = False
        self._materialized = False
        # Snapshot the metadata at construction time so the started_at
        # timestamp reflects when the run was *allocated*, not when its
        # first day was recorded. Written out by `_materialize`.
        self._metadata_payload: dict[str, Any] = {
            "run_id": self.run_id,
            "seed": int(seed),
            "scenario": scenario_name,
            "session": session,
            "started_at": time.time(),
        }

    def _materialize(self) -> None:
        """Create the run folder and write metadata.json on first use.
        Idempotent — subsequent calls are no-ops."""
        if self._materialized:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(json.dumps(self._metadata_payload) + "\n")
        self._materialized = True

    def record_step(self, world: World, day: int) -> None:
        """Append one line to states.jsonl after a successful simulated day.

        `day` is the just-completed day; the embedded `state` snapshot is
        the world's end-of-day view via `state_dict()`. The per-day
        summary mirrors `state.today` — same fields the UI's step
        response and the daily P&L surface.
        """
        self._materialize()
        entry = {
            "day": int(day),
            "state": world.state_dict(),
            "summary": world.state.today.model_dump(),
        }
        with self.states_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=_json_default) + "\n")

    def finalize(self, world: World) -> None:
        """Write final.json exactly once. Repeated calls are no-ops.

        A recorder that was never materialized (no `record_step`) stays
        invisible on disk — finalize doesn't force the metadata write
        for a zero-day run.
        """
        if self._finalized:
            return
        self._finalized = True
        if not self._materialized:
            return
        payload = {
            "run_id": self.run_id,
            "final_state": world.state_dict(),
            "ended_at": time.time(),
        }
        self.final_path.write_text(json.dumps(payload, default=_json_default) + "\n")


def _new_run_id() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)
