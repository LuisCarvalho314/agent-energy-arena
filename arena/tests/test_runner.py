"""End-to-end integration test for `arena.runner`.

Runs the scripted reference agent against `scenarios.baseline` via the
runner CLI and asserts the result row matches the committed baseline
under `baselines/arena/`. The runner shells out to `python
evaluate.py ...` for each pair, so the test is intentionally slow
(~1 s) — fast enough for the default suite but slower than the
in-process replay tests.

Byte-match against the committed `baselines/arena/<scenario>-<seed>.json`
files is enforced here. If the scripted agent or scenario semantics
change in a way that shifts the deterministic outputs, run
`make baselines` to regenerate the committed files and commit the diff
in the same change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.baselines import BASELINE_GAME_DAYS, baseline_path, to_baseline_dict
from arena.results import ArenaResult, read_results
from arena.runner import main, run_pair


def _short_game(monkeypatch: pytest.MonkeyPatch, days: int = BASELINE_GAME_DAYS) -> None:
    monkeypatch.setenv("GAME_DAYS", str(days))
    monkeypatch.setenv("MANUAL_GAME_DAYS", str(days))


def test_run_pair_scripted_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_pair() returns a populated ArenaResult for scripted × baseline."""
    _short_game(monkeypatch)
    result = run_pair("agents.scripted", "scenarios.baseline", cwd=tmp_path)
    assert isinstance(result, ArenaResult)
    assert result.agent == "agents.scripted"
    assert result.scenario == "scenarios.baseline"
    assert result.seed == 42
    assert result.population > 0
    assert 0.0 <= result.renewable_share <= 1.0
    assert result.run_id
    # The recorded run folder exists alongside the runner's cwd.
    assert (tmp_path / "runs" / result.run_id / "final_state.json").exists()

    # Byte-match the deterministic subset against the committed baseline.
    committed = json.loads(baseline_path(result.scenario, result.seed).read_text())
    assert to_baseline_dict(result) == committed


def test_runner_cli_writes_results_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`python -m arena.runner` writes a JSON file that round-trips through read_results."""
    _short_game(monkeypatch, days=30)
    output = tmp_path / "results.json"
    rc = main(
        [
            "--agent",
            "agents.scripted",
            "--scenario",
            "scenarios.baseline",
            "--output",
            str(output),
            "--cwd",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert output.exists()

    # Stdout carries a single JSON line summarizing the write.
    last_line = capsys.readouterr().out.strip().splitlines()[-1]
    summary = json.loads(last_line)
    assert summary["results"] == 1
    assert summary["output"] == str(output)

    rows = read_results(output)
    assert len(rows) == 1
    assert rows[0].agent == "agents.scripted"
    assert rows[0].scenario == "scenarios.baseline"
    assert rows[0].seed == 42
