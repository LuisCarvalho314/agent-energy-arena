"""Pure-function tests for `arena.leaderboard` aggregation.

Covers known input → known ranking, fractional-rank tie semantics, the
missing-agent policy (agents excluded from a scenario rank but included
in others), and final tie-breaking on mean raw score then submission
timestamp.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arena.baselines import BASELINES_DIR, baseline_path, scenario_short_name
from arena.leaderboard import (
    build_table,
    main,
    rank_agents,
    read_baselines_dir,
    render_leaderboard,
)
from arena.results import ArenaResult
from arena.runner import REPO_ROOT


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


def _write_fake_baseline(directory: Path, agent: str, scenario: str, raw_score: float) -> Path:
    """Write a deterministic-subset baseline JSON file to `directory`.

    Mirrors `arena.baselines.to_baseline_dict` so the CLI-rendering tests
    do not depend on the committed baselines (those drift over time).
    """
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent": agent,
        "scenario": scenario,
        "seed": 42,
        "population": 100.0,
        "treasury_delta": -1000.0,
        "renewable_share": 0.5,
        "raw_score": raw_score,
    }
    path = directory / f"{scenario_short_name(scenario)}-42.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def test_read_baselines_dir_lifts_baseline_json(tmp_path: Path) -> None:
    """`read_baselines_dir` reads every `*.json` in the dir into ArenaResults."""
    _write_fake_baseline(tmp_path, "agents.scripted", "scenarios.baseline", 0.30)
    _write_fake_baseline(tmp_path, "agents.scripted", "scenarios.grid_stress", 0.25)

    results = read_baselines_dir(tmp_path)
    by_scenario = {r.scenario: r for r in results}
    assert set(by_scenario) == {"scenarios.baseline", "scenarios.grid_stress"}
    assert by_scenario["scenarios.baseline"].raw_score == 0.30
    # `run_id` / `submitted_at` are synthesized — pinning here keeps the
    # contract explicit for the CLI's downstream rendering.
    assert by_scenario["scenarios.baseline"].run_id == ""
    assert by_scenario["scenarios.baseline"].submitted_at == 0.0


def test_render_leaderboard_is_deterministic(tmp_path: Path) -> None:
    """Same baselines → byte-identical rendered Markdown."""
    _write_fake_baseline(tmp_path, "agents.scripted", "scenarios.baseline", 0.30)
    _write_fake_baseline(tmp_path, "agents.scripted", "scenarios.grid_stress", 0.25)

    first = render_leaderboard(read_baselines_dir(tmp_path))
    second = render_leaderboard(read_baselines_dir(tmp_path))
    assert first == second
    # Sanity-check the rendered shape — header, table, submission section.
    assert "# Leaderboard" in first
    assert "| # | Agent" in first
    assert "agents.scripted" in first
    assert "Submitting an agent" in first


def test_main_cli_writes_output(tmp_path: Path) -> None:
    """`python -m arena.leaderboard --baselines-dir X --output Y` writes Y."""
    _write_fake_baseline(tmp_path, "agents.scripted", "scenarios.baseline", 0.30)
    out_path = tmp_path / "OUT.md"

    rc = main(["--baselines-dir", str(tmp_path), "--output", str(out_path)])
    assert rc == 0
    rendered = out_path.read_text()
    assert "# Leaderboard" in rendered
    assert "agents.scripted" in rendered


def test_cli_against_committed_baselines_byte_match() -> None:
    """`python -m arena.leaderboard --stdout` matches the committed file.

    Acts as the regression sentinel for `LEADERBOARD.md`: if the committed
    baselines drift, this fails until `make leaderboard` is rerun and the
    refreshed Markdown is committed.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "arena.leaderboard", "--stdout"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    committed = (REPO_ROOT / "LEADERBOARD.md").read_text()
    assert proc.stdout == committed


def test_committed_baselines_render_one_scripted_row() -> None:
    """The three committed baselines aggregate into one ranked row."""
    # Don't assume the score values — just shape and presence.
    for scenario in (
        "scenarios.baseline",
        "scenarios.grid_stress",
        "scenarios.economy_stress",
    ):
        assert baseline_path(scenario, 42).exists(), scenario

    results = read_baselines_dir(BASELINES_DIR)
    rendered = render_leaderboard(results)
    # One agent (`agents.scripted`) on three scenarios → one ranked row,
    # mean rank 1.00 (no other agents to rank against).
    assert rendered.count("| 1 | agents.scripted") == 1
    assert "1.00" in rendered
