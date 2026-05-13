"""End-to-end integration test for `arena.runner`.

Runs the scripted reference agent against `scenarios.baseline` via the
runner CLI and asserts the result row carries the expected fields. The
runner shells out to `python evaluate.py ...` for each pair, so the
test is intentionally slow (~5 s) — fast enough for the default
suite but slower than the in-process replay tests.

A byte-match comparison against a committed baseline result file is
out of scope here (issue 08 commits those files); this test asserts
that the runner produces a structurally valid result for the public
scripted × baseline pair on a shortened 30-day game.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.results import ArenaResult, read_results
from arena.runner import main, run_pair


def _short_game(monkeypatch: pytest.MonkeyPatch, days: int = 30) -> None:
    monkeypatch.setenv("GAME_DAYS", str(days))
    monkeypatch.setenv("MANUAL_GAME_DAYS", str(days))


def test_run_pair_scripted_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_pair() returns a populated ArenaResult for scripted × baseline."""
    _short_game(monkeypatch, days=30)
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
