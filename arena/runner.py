"""Subprocess-isolated `(agent, scenario)` runner.

Each pair is executed in its own `python evaluate.py --agent <A>
--scenario <S> --seed <Z>` subprocess so a misbehaving agent cannot
poison the eval. The runner parses each subprocess's JSON output line
and reads `final_state.json` from the recorded run folder to derive
the `ArenaResult` row.

CLI:

    python -m arena.runner \\
        --agent agents.scripted \\
        --scenario scenarios.baseline \\
        --output results.json

`--agent` and `--scenario` may be passed multiple times; the runner
evaluates every Cartesian pair. Each pair's seed is read from the
scenario class's `seed` attribute (the `Scenario` base class declares
`seed: int = 42`; subclasses override).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from arena.results import ArenaResult, write_results
from world.scenario import load_scenario

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
EVALUATE_PY: Path = REPO_ROOT / "evaluate.py"


def _seed_for(scenario_path: str) -> int:
    """Read `cls.seed` from the loaded scenario instance."""
    return int(load_scenario(scenario_path).seed)


def _result_from_run(
    *,
    agent: str,
    scenario: str,
    seed: int,
    run_dir: Path,
    raw_score: float,
    submitted_at: float,
) -> ArenaResult:
    """Pull population / treasury delta / renewable share off `final_state.json`."""
    final_state = json.loads((run_dir / "final_state.json").read_text())
    starting_cash = float(final_state["config"]["starting_cash"])
    population = float(final_state["population"])
    treasury_delta = float(final_state["treasury"]) - starting_cash
    total_kwh = float(final_state.get("cumulative_total_served_kwh", 0.0))
    renewable_kwh = float(final_state.get("cumulative_renewable_served_kwh", 0.0))
    renewable_share = renewable_kwh / max(total_kwh, 1.0)
    return ArenaResult(
        agent=agent,
        scenario=scenario,
        seed=seed,
        population=population,
        treasury_delta=treasury_delta,
        renewable_share=renewable_share,
        raw_score=raw_score,
        run_id=run_dir.name,
        submitted_at=submitted_at,
    )


def run_pair(
    agent: str,
    scenario: str,
    *,
    seed: int | None = None,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> ArenaResult:
    """Run one `(agent, scenario)` pair as a subprocess; return the result row.

    `cwd` is the directory the subprocess runs in; `runs/` is created
    relative to it. Defaults to the current working directory.
    `seed` defaults to the scenario class's `seed` attribute.
    """
    if seed is None:
        seed = _seed_for(scenario)
    work_dir = Path(cwd) if cwd is not None else Path.cwd()
    work_dir.mkdir(parents=True, exist_ok=True)

    import os

    env = os.environ.copy()
    # Ensure the subprocess can import the in-repo packages even when
    # `work_dir` is a temp dir without the project on sys.path.
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{pythonpath}" if pythonpath else str(REPO_ROOT)
    if extra_env:
        env.update(extra_env)

    cmd = [
        sys.executable,
        str(EVALUATE_PY),
        "--agent",
        agent,
        "--scenario",
        scenario,
        "--seed",
        str(seed),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(work_dir),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # The last stdout line is evaluate.py's score-breakdown JSON. Earlier
    # lines (if any) are agent-side prints; we ignore them.
    last_line = proc.stdout.strip().splitlines()[-1]
    payload: dict[str, Any] = json.loads(last_line)
    run_id = str(payload["run_id"])
    score_block = payload.get("score") or {}
    raw_score = float(score_block.get("score", 0.0))
    run_dir = work_dir / "runs" / run_id
    return _result_from_run(
        agent=agent,
        scenario=scenario,
        seed=seed,
        run_dir=run_dir,
        raw_score=raw_score,
        submitted_at=time.time(),
    )


def run_pairs(
    agents: list[str],
    scenarios: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[ArenaResult]:
    """Sequentially evaluate the Cartesian `(agent, scenario)` product."""
    results: list[ArenaResult] = []
    for agent in agents:
        for scenario in scenarios:
            results.append(run_pair(agent, scenario, cwd=cwd, extra_env=extra_env))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        action="append",
        required=True,
        help="Dotted module path of the agent (repeatable).",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        required=True,
        help="Dotted module path of the scenario (repeatable).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the results JSON file.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for subprocesses (defaults to current).",
    )
    args = parser.parse_args(argv)

    results = run_pairs(list(args.agent), list(args.scenario), cwd=args.cwd)
    write_results(results, args.output)
    print(json.dumps({"results": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
