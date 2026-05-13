"""Per-scenario baseline regression tests.

Verifies the committed `baselines/arena/<scenario>-<seed>.json` files
exist for every public scenario and round-trip byte-for-byte through
`arena.baselines.regenerate`. If the scripted agent or any scenario
shifts deterministic outputs, this test fails and `make baselines`
must be re-run to refresh the committed files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.baselines import (
    BASELINE_AGENT,
    BASELINE_GAME_DAYS,
    BASELINES_DIR,
    PUBLIC_SCENARIOS,
    baseline_path,
    read_baseline,
    regenerate,
    scenario_short_name,
    to_baseline_dict,
)
from arena.runner import run_pair


def _short_game(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAME_DAYS", str(BASELINE_GAME_DAYS))
    monkeypatch.setenv("MANUAL_GAME_DAYS", str(BASELINE_GAME_DAYS))


def test_every_public_scenario_has_a_committed_baseline() -> None:
    """One file per (public scenario, seed=42)."""
    for scenario in PUBLIC_SCENARIOS:
        path = baseline_path(scenario, seed=42)
        assert path.exists(), f"missing committed baseline at {path}"
        assert path.parent == BASELINES_DIR


def test_committed_baselines_match_canonical_schema() -> None:
    """Every committed baseline carries exactly the deterministic-subset keys."""
    expected_keys = {
        "agent",
        "scenario",
        "seed",
        "population",
        "treasury_delta",
        "renewable_share",
        "raw_score",
    }
    for scenario in PUBLIC_SCENARIOS:
        payload = read_baseline(baseline_path(scenario, seed=42))
        assert set(payload.keys()) == expected_keys
        assert payload["agent"] == BASELINE_AGENT
        assert payload["scenario"] == scenario
        assert payload["seed"] == 42


def test_scenario_short_name_strips_dotted_prefix() -> None:
    assert scenario_short_name("scenarios.baseline") == "baseline"
    assert scenario_short_name("scenarios.grid_stress") == "grid_stress"
    assert scenario_short_name("a.b.c.d") == "d"


def test_baseline_path_encodes_scenario_and_seed() -> None:
    path = baseline_path("scenarios.grid_stress", seed=42)
    assert path.name == "grid_stress-42.json"
    assert path.parent == BASELINES_DIR


def test_run_pair_matches_every_committed_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For every public scenario, the scripted agent's row byte-matches the file."""
    _short_game(monkeypatch)
    for scenario in PUBLIC_SCENARIOS:
        result = run_pair(BASELINE_AGENT, scenario, cwd=tmp_path)
        committed = read_baseline(baseline_path(scenario, result.seed))
        assert to_baseline_dict(result) == committed


def test_regenerate_overwrites_to_isolated_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`regenerate` writes one file per scenario; rerun overwrites byte-identically."""
    # Redirect BASELINES_DIR to tmp so the test does not touch the repo's
    # committed files. baseline_path() reads BASELINES_DIR at call time.
    fake_dir = tmp_path / "baselines" / "arena"
    monkeypatch.setattr("arena.baselines.BASELINES_DIR", fake_dir)

    first = regenerate(cwd=tmp_path)
    assert len(first) == len(PUBLIC_SCENARIOS)
    for path in first:
        assert path.parent == fake_dir
        assert path.exists()

    snapshots = {p: p.read_text() for p in first}

    # Rerun — the deterministic subset must be byte-identical across runs.
    second = regenerate(cwd=tmp_path)
    assert second == first
    for path in second:
        assert path.read_text() == snapshots[path]

    # The committed files are valid JSON of the expected shape.
    for path in second:
        payload = json.loads(path.read_text())
        assert payload["agent"] == BASELINE_AGENT
        assert payload["seed"] == 42
