"""Per-scenario scripted-agent baselines.

A *baseline* is the deterministic subset of an `ArenaResult` committed to
`baselines/arena/<scenario_short>-<seed>.json`. It anchors the arena
integration test (which verifies the scripted reference agent's
`(population, treasury_delta, renewable_share, raw_score)` byte-match
the committed file for each public scenario) and gives leaderboard
consumers a stable reference row.

Non-deterministic fields (`run_id`, `submitted_at`) are stripped — the
baseline JSON is a 7-field document of (agent, scenario, seed,
population, treasury_delta, renewable_share, raw_score).

Game length: baselines are regenerated at `BASELINE_GAME_DAYS=30`. The
short window matches the existing arena integration test pattern and
keeps `make baselines` + the per-scenario regression test in the
sub-second range. Full-game (`GAME_DAYS=3650`) baselines are NOT
committed; if a future slice needs leaderboard-quality references they
should land under a sibling directory (e.g. `baselines/arena-full/`)
rather than overwriting the regression sentinels.

CLI:

    python -m arena.baselines

Regenerates every public-scenario baseline by running the scripted
reference agent (`agents.scripted`) against each scenario via the
arena runner. Writes one JSON file per `(scenario, seed)` pair under
`baselines/arena/`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from arena.results import ArenaResult
from arena.runner import REPO_ROOT, run_pair

BASELINES_DIR: Path = REPO_ROOT / "baselines" / "arena"

BASELINE_AGENT: str = "agents.scripted"

PUBLIC_SCENARIOS: tuple[str, ...] = (
    "scenarios.baseline",
    "scenarios.grid_stress",
    "scenarios.economy_stress",
)

BASELINE_GAME_DAYS: int = 30


def scenario_short_name(scenario_path: str) -> str:
    """Last dotted-path segment — e.g. `scenarios.grid_stress` → `grid_stress`."""
    return scenario_path.rsplit(".", 1)[-1]


def baseline_path(scenario_path: str, seed: int) -> Path:
    """Committed path: `baselines/arena/<scenario_short>-<seed>.json`."""
    return BASELINES_DIR / f"{scenario_short_name(scenario_path)}-{seed}.json"


def to_baseline_dict(result: ArenaResult) -> dict[str, Any]:
    """Strip non-deterministic fields (`run_id`, `submitted_at`) from a result."""
    return {
        "agent": result.agent,
        "scenario": result.scenario,
        "seed": result.seed,
        "population": result.population,
        "treasury_delta": result.treasury_delta,
        "renewable_share": result.renewable_share,
        "raw_score": result.raw_score,
    }


def write_baseline(result: ArenaResult, path: Path) -> None:
    """Serialize the deterministic subset of `result` to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_baseline_dict(result), indent=2, sort_keys=True) + "\n")


def read_baseline(path: Path) -> dict[str, Any]:
    """Parse a baseline JSON file produced by `write_baseline`."""
    payload: dict[str, Any] = json.loads(path.read_text())
    return payload


def _short_game_env() -> dict[str, str]:
    """Env-var overrides that pin the scripted run to `BASELINE_GAME_DAYS`."""
    return {
        "GAME_DAYS": str(BASELINE_GAME_DAYS),
        "MANUAL_GAME_DAYS": str(BASELINE_GAME_DAYS),
    }


def regenerate(
    *,
    agent: str = BASELINE_AGENT,
    scenarios: tuple[str, ...] = PUBLIC_SCENARIOS,
    cwd: Path | None = None,
) -> list[Path]:
    """Re-run scripted × each scenario, overwrite each committed baseline.

    Returns the list of written paths. `cwd` is forwarded to `run_pair`
    (defaults to the current working directory); `runs/` is created
    relative to it. Tests pass `tmp_path` to keep regenerated runs out
    of the repo's `runs/` directory.
    """
    written: list[Path] = []
    for scenario in scenarios:
        result = run_pair(agent, scenario, cwd=cwd, extra_env=_short_game_env())
        path = baseline_path(scenario, result.seed)
        write_baseline(result, path)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for subprocesses (defaults to current).",
    )
    args = parser.parse_args(argv)

    written = regenerate(cwd=args.cwd)
    # Strip the repo prefix for a tidy log line.
    rel = [str(p.relative_to(REPO_ROOT)) if p.is_absolute() else str(p) for p in written]
    print(json.dumps({"baselines": rel, "agent": BASELINE_AGENT, "days": BASELINE_GAME_DAYS}))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
