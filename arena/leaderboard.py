"""Pure-function leaderboard: mean-rank across scenarios.

The arena's aggregation rule (PRD §"Score formula and arena aggregation"):

  - For each scenario, rank agents by raw score (highest first). Ties
    share a fractional rank (e.g. two tied at position 1 each get
    rank 1.5).
  - An agent's arena rank is the mean of its per-scenario ranks across
    the scenarios it appeared in. Agents missing from a scenario are
    excluded from that scenario's rank but included in others.
  - Final ordering: mean rank ascending; ties break on mean raw score
    (higher wins), then on earliest submission timestamp.

`build_table` returns a Markdown table; `rank_agents` returns the
structured rows so callers (e.g. a hosted-leaderboard renderer) can
consume the same aggregation without parsing Markdown.

A CLI (`python -m arena.leaderboard`) reads the committed per-scenario
baselines under `baselines/arena/` and renders the repo's
`LEADERBOARD.md`. The CLI is deterministic: same baselines in → byte-
identical Markdown out, so committing the regenerated file is safe.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from arena.results import ArenaResult


@dataclasses.dataclass(frozen=True)
class AgentRow:
    """Aggregated row for one agent across all scenarios it appeared in."""

    agent: str
    mean_rank: float
    mean_raw_score: float
    submitted_at: float
    scenarios: tuple[str, ...]


def _per_scenario_ranks(results: Iterable[ArenaResult]) -> dict[str, dict[str, float]]:
    """Map scenario → {agent: fractional rank}.

    Fractional ranking: agents tied at a position share the mean of the
    positions they collectively occupy (positions 2 and 3 → both get
    rank 2.5). This is the standard "mean rank" convention for
    benchmark aggregation.
    """
    by_scenario: dict[str, list[ArenaResult]] = defaultdict(list)
    for r in results:
        by_scenario[r.scenario].append(r)

    ranks: dict[str, dict[str, float]] = {}
    for scenario, rows in by_scenario.items():
        # Sort by raw_score descending. Ties broken arbitrarily here —
        # fractional ranking below collapses them onto a shared value.
        sorted_rows = sorted(rows, key=lambda r: -r.raw_score)
        agent_to_rank: dict[str, float] = {}
        i = 0
        while i < len(sorted_rows):
            j = i
            while (
                j + 1 < len(sorted_rows)
                and sorted_rows[j + 1].raw_score == sorted_rows[i].raw_score
            ):
                j += 1
            shared = (i + 1 + j + 1) / 2.0  # mean of 1-based positions i+1..j+1
            for k in range(i, j + 1):
                agent_to_rank[sorted_rows[k].agent] = shared
            i = j + 1
        ranks[scenario] = agent_to_rank
    return ranks


def rank_agents(results: Iterable[ArenaResult]) -> list[AgentRow]:
    """Aggregate per-pair results into per-agent rows, sorted by mean rank.

    Pure function: deterministic, no I/O.
    """
    rows = list(results)
    scenario_ranks = _per_scenario_ranks(rows)

    by_agent: dict[str, list[ArenaResult]] = defaultdict(list)
    for r in rows:
        by_agent[r.agent].append(r)

    agent_rows: list[AgentRow] = []
    for agent, agent_results in by_agent.items():
        ranks = [scenario_ranks[r.scenario][agent] for r in agent_results]
        mean_rank = sum(ranks) / len(ranks)
        mean_score = sum(r.raw_score for r in agent_results) / len(agent_results)
        earliest = min(r.submitted_at for r in agent_results)
        scenarios = tuple(sorted({r.scenario for r in agent_results}))
        agent_rows.append(
            AgentRow(
                agent=agent,
                mean_rank=mean_rank,
                mean_raw_score=mean_score,
                submitted_at=earliest,
                scenarios=scenarios,
            )
        )

    # Mean rank ascending; ties → higher mean score; ties → earlier submission.
    agent_rows.sort(key=lambda a: (a.mean_rank, -a.mean_raw_score, a.submitted_at))
    return agent_rows


def build_table(results: Iterable[ArenaResult]) -> str:
    """Produce a Markdown ranked table from `(agent, scenario)` results.

    Columns: rank #, agent, mean rank, mean raw score, scenarios played.
    Empty input returns an empty-table stub with just the header so a
    consumer (e.g. `LEADERBOARD.md`) renders sensibly before any agents
    have been scored.
    """
    rows = rank_agents(results)
    header = (
        "| # | Agent | Mean Rank | Mean Score | Scenarios |\n"
        "|---|-------|-----------|------------|-----------|\n"
    )
    if not rows:
        return header
    lines: list[str] = []
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | {row.agent} | {row.mean_rank:.2f} | "
            f"{row.mean_raw_score:.4f} | {', '.join(row.scenarios)} |"
        )
    return header + "\n".join(lines) + "\n"


def _result_from_baseline_dict(payload: dict[str, Any]) -> ArenaResult:
    """Lift a baseline JSON payload to an `ArenaResult`.

    Committed baselines under `baselines/arena/` strip `run_id` and
    `submitted_at` (the two non-deterministic fields). The leaderboard
    uses `submitted_at` only as the final tie-break; pinning it to 0.0
    means baselines tie at "earliest submission", which is the right
    semantics for a reproducible repo-committed leaderboard.
    """
    return ArenaResult(
        agent=str(payload["agent"]),
        scenario=str(payload["scenario"]),
        seed=int(payload["seed"]),
        population=float(payload["population"]),
        treasury_delta=float(payload["treasury_delta"]),
        renewable_share=float(payload["renewable_share"]),
        raw_score=float(payload["raw_score"]),
        run_id="",
        submitted_at=0.0,
    )


def read_baselines_dir(directory: Path) -> list[ArenaResult]:
    """Read every `*.json` baseline under `directory` into `ArenaResult`s.

    The committed baseline shape (see `arena.baselines.to_baseline_dict`)
    is the canonical input for the repo's leaderboard. Files are sorted
    by path for stable iteration so a regenerated `LEADERBOARD.md` is
    byte-identical across machines.
    """
    import json

    rows: list[ArenaResult] = []
    for path in sorted(directory.glob("*.json")):
        payload: dict[str, Any] = json.loads(path.read_text())
        rows.append(_result_from_baseline_dict(payload))
    return rows


def render_leaderboard(results: Iterable[ArenaResult]) -> str:
    """Render the repo's `LEADERBOARD.md` content from arena results.

    Wraps `build_table` with the heading, regeneration note, and the
    cross-links a docs reader expects. Deterministic: no timestamps or
    machine-specific paths leak into the output.
    """
    table = build_table(results)
    return (
        "# Leaderboard\n"
        "\n"
        "Mean-rank aggregation across the v1 public scenarios "
        "(`scenarios.baseline`, `scenarios.grid_stress`, "
        "`scenarios.economy_stress`) on seed 42.\n"
        "\n"
        "See [SCENARIOS.md](SCENARIOS.md) for the scenario taxonomy and "
        "[RULES.md](RULES.md#scoring) for the score formula. The mean-rank "
        "tie-break order is mean raw score (higher wins), then earliest "
        "submission timestamp.\n"
        "\n"
        "Regenerate with `python -m arena.leaderboard` after `make baselines`. "
        "The committed file is byte-identical to the regenerated one given the "
        "same `baselines/arena/` contents.\n"
        "\n"
        f"{table}"
        "\n"
        "## Submitting an agent\n"
        "\n"
        "Community agents live under `agents/community/<your_handle>.py`. "
        "See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR-as-submission flow. "
        "A maintainer regenerates this file on merge.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help="Directory of baseline JSON files (default: <repo>/baselines/arena).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write rendered Markdown to this path (default: <repo>/LEADERBOARD.md).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print rendered Markdown to stdout instead of writing a file.",
    )
    args = parser.parse_args(argv)

    # Resolve the repo root via `arena.baselines` so callers from any cwd
    # land on the same path. Imported lazily to avoid a hard dep when the
    # leaderboard is consumed as a pure function.
    from arena.baselines import BASELINES_DIR
    from arena.runner import REPO_ROOT

    baselines_dir = args.baselines_dir or BASELINES_DIR
    results = read_baselines_dir(baselines_dir)
    rendered = render_leaderboard(results)

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    output = args.output or (REPO_ROOT / "LEADERBOARD.md")
    output.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
