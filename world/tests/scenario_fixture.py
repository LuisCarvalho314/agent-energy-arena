"""Test-only scenario fixture for issue 04 API attach + replay tests.

Lives as a real importable module (not a sys.modules monkeypatch) so the
loader's `importlib.import_module` works the same way it does for shipped
scenarios under `scenarios/`. The scenario writes a deterministic trace
entry on day 0 so tests can assert the day-loop hook ran end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.scenario import Scenario

if TYPE_CHECKING:
    from world.sim import World


class TraceScenario(Scenario):
    seed = 42

    def apply(self, world: World, day: int) -> None:
        if day == 0:
            world.state.scenario_trace.append({"day": 0, "marker": "fixture-fired"})
