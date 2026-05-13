"""ArenaResult dataclass + JSON I/O.

One ArenaResult per `(agent, scenario, seed)` row. The arena runner
captures these from each subprocess and writes them to a single JSON
file consumed by `arena.leaderboard`. The schema is stable: an external
auditor can read the JSON without importing this package.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


@dataclasses.dataclass(frozen=True)
class ArenaResult:
    """One `(agent, scenario, seed)` evaluation row.

    - `agent`: dotted module path passed to `evaluate.py --agent`.
    - `scenario`: dotted module path passed to `evaluate.py --scenario`.
    - `seed`: integer seed the world was reset with.
    - `population`: final-state population (P term input).
    - `treasury_delta`: final treasury minus starting cash (T term input).
    - `renewable_share`: cumulative renewable kWh / cumulative total kWh.
    - `raw_score`: composite score from the score breakdown (0.5*p + 0.4*t + 0.1*r).
    - `run_id`: post-reset recorder run folder name.
    - `submitted_at`: unix timestamp the result was captured.
    """

    agent: str
    scenario: str
    seed: int
    population: float
    treasury_delta: float
    renewable_share: float
    raw_score: float
    run_id: str
    submitted_at: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArenaResult:
        return cls(
            agent=str(payload["agent"]),
            scenario=str(payload["scenario"]),
            seed=int(payload["seed"]),
            population=float(payload["population"]),
            treasury_delta=float(payload["treasury_delta"]),
            renewable_share=float(payload["renewable_share"]),
            raw_score=float(payload["raw_score"]),
            run_id=str(payload["run_id"]),
            submitted_at=float(payload["submitted_at"]),
        )


def write_results(results: list[ArenaResult], path: Path) -> None:
    """Serialize a list of `ArenaResult`s to disk as a JSON array."""
    payload = [r.to_dict() for r in results]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_results(path: Path) -> list[ArenaResult]:
    """Parse a JSON-array file produced by `write_results`."""
    payload = json.loads(path.read_text())
    return [ArenaResult.from_dict(row) for row in payload]
