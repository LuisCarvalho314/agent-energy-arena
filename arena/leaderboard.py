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
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable

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
