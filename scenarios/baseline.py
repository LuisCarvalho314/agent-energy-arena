"""Baseline scenario — identity run on seed 42.

Kept as a class so the CLI surface is uniform with the stress
scenarios: `evaluate.py --scenario scenarios.baseline` and
`evaluate.py --scenario scenarios.grid_stress` go through the same
loader, the same /reset shape, and produce the same metadata.json
layout. The body inherits `NullScenario.apply` (no-op), so the byte
trace of a `scenarios.baseline` run is identical to a run with no
`--scenario` flag at all.
"""

from __future__ import annotations

from world.scenario import NullScenario


class Baseline(NullScenario):
    """Identity scenario — no overrides, no event injections.

    Runs the world on its default seed-42 trajectory. The class exists
    so the arena runner / CLI / metadata.json can carry the dotted
    path `scenarios.baseline` rather than a bare `None` or the
    `world.scenario.NullScenario` fallback that every fresh world
    already attaches.
    """

    seed: int = 42
