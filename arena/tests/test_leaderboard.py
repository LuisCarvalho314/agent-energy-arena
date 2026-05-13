"""Pure-function tests for `arena.leaderboard` aggregation.

Covers known input → known ranking, fractional-rank tie semantics, the
missing-agent policy (agents excluded from a scenario rank but included
in others), and final tie-breaking on mean raw score then submission
timestamp.
"""

from __future__ import annotations

from arena.leaderboard import build_table, rank_agents
from arena.results import ArenaResult


def _r(
    agent: str,
    scenario: str,
    raw_score: float,
    *,
    submitted_at: float = 1000.0,
) -> ArenaResult:
    return ArenaResult(
        agent=agent,
        scenario=scenario,
        seed=42,
        population=0.0,
        treasury_delta=0.0,
        renewable_share=0.0,
        raw_score=raw_score,
        run_id=f"{agent}-{scenario}",
        submitted_at=submitted_at,
    )


def test_two_scenarios_known_ranking() -> None:
    """A wins both → mean rank 1.0 → ranked first."""
    results = [
        _r("A", "s1", 1.0),
        _r("B", "s1", 0.5),
        _r("C", "s1", 0.2),
        _r("A", "s2", 0.9),
        _r("B", "s2", 0.4),
        _r("C", "s2", 0.7),
    ]
    rows = rank_agents(results)
    assert rows[0].agent == "A"
    assert rows[0].mean_rank == 1.0
    # C is rank 3 in s1, rank 2 in s2 → mean 2.5; B is 2 then 3 → 2.5.
    # Mean raw score is also equal (0.45 each), and submit timestamps
    # match — so B and C are a true tie; only the shared rank is pinned.
    assert {rows[1].agent, rows[2].agent} == {"B", "C"}
    assert rows[1].mean_rank == rows[2].mean_rank == 2.5


def test_fractional_rank_for_ties() -> None:
    """Two agents tied at the top each get rank 1.5, not 1."""
    results = [
        _r("A", "s1", 1.0),
        _r("B", "s1", 1.0),
        _r("C", "s1", 0.5),
    ]
    rows = rank_agents(results)
    rank_by_agent = {r.agent: r.mean_rank for r in rows}
    assert rank_by_agent["A"] == 1.5
    assert rank_by_agent["B"] == 1.5
    assert rank_by_agent["C"] == 3.0


def test_missing_agent_excluded_from_that_scenario_only() -> None:
    """C is missing from s2. C's mean rank uses only s1 (rank 1); A & B span both."""
    results = [
        _r("A", "s1", 0.5),
        _r("B", "s1", 0.3),
        _r("C", "s1", 1.0),
        _r("A", "s2", 1.0),
        _r("B", "s2", 0.5),
    ]
    rows = rank_agents(results)
    by_agent = {r.agent: r for r in rows}
    assert by_agent["C"].mean_rank == 1.0  # only ranked in s1
    assert by_agent["C"].scenarios == ("s1",)
    assert by_agent["A"].mean_rank == 1.5  # s1: 2, s2: 1
    assert by_agent["A"].scenarios == ("s1", "s2")
    assert by_agent["B"].mean_rank == 2.5


def test_tie_break_by_mean_raw_score() -> None:
    """Two agents with identical mean rank → higher mean score wins."""
    # A: ranks (1,2) → mean 1.5, mean_score = (1.0 + 0.4) / 2 = 0.7
    # B: ranks (2,1) → mean 1.5, mean_score = (0.5 + 0.9) / 2 = 0.7 ← exact tie
    # C: ranks (3,3) → mean 3.0
    # To force a clean test we use different score totals:
    results = [
        _r("A", "s1", 1.0),
        _r("A", "s2", 0.4),
        _r("B", "s1", 0.5),
        _r("B", "s2", 0.9),  # B mean_score 0.7
        _r("C", "s1", 0.3),
        _r("C", "s2", 0.2),
    ]
    # Bump A so it has higher mean_score: 1.0 + 0.5 = 0.75 mean.
    results[1] = _r("A", "s2", 0.5)
    rows = rank_agents(results)
    # A: ranks (1,2)=1.5, score mean=0.75. B: ranks (2,1)=1.5, score mean=0.7.
    assert rows[0].agent == "A"
    assert rows[1].agent == "B"


def test_tie_break_by_submission_timestamp() -> None:
    """Identical mean rank AND mean score → earlier submission wins."""
    results = [
        _r("A", "s1", 1.0, submitted_at=200.0),
        _r("B", "s1", 0.5, submitted_at=100.0),
        _r("A", "s2", 0.5, submitted_at=200.0),
        _r("B", "s2", 1.0, submitted_at=100.0),
    ]
    rows = rank_agents(results)
    # Both have rank mean 1.5 and score mean 0.75. B submitted earlier.
    assert rows[0].agent == "B"
    assert rows[1].agent == "A"


def test_build_table_markdown_shape() -> None:
    """Markdown table has header + one row per agent in ranked order."""
    table = build_table(
        [
            _r("A", "s1", 1.0),
            _r("B", "s1", 0.5),
        ]
    )
    lines = table.strip().splitlines()
    assert lines[0].startswith("| # | Agent")
    assert lines[1].startswith("|---")
    assert "A" in lines[2] and "1.00" in lines[2]
    assert "B" in lines[3] and "2.00" in lines[3]


def test_build_table_empty_results() -> None:
    """No results → header-only stub, not a crash."""
    table = build_table([])
    assert "| # | Agent" in table
    assert table.strip().splitlines()[1].startswith("|---")
