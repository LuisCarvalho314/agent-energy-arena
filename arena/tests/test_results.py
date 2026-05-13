"""Round-trip tests for ArenaResult JSON I/O."""

from __future__ import annotations

from pathlib import Path

from arena.results import ArenaResult, read_results, write_results


def _make(agent: str = "agents.scripted", scenario: str = "scenarios.baseline") -> ArenaResult:
    return ArenaResult(
        agent=agent,
        scenario=scenario,
        seed=42,
        population=204.0,
        treasury_delta=-1_695_338.09,
        renewable_share=0.13,
        raw_score=0.42,
        run_id="2026-05-13-abc",
        submitted_at=1_715_600_000.0,
    )


def test_to_from_dict_roundtrip() -> None:
    row = _make()
    parsed = ArenaResult.from_dict(row.to_dict())
    assert parsed == row


def test_write_then_read_preserves_order_and_values(tmp_path: Path) -> None:
    rows = [_make(agent="agents.scripted"), _make(agent="agents.langgraph_agent")]
    path = tmp_path / "results.json"
    write_results(rows, path)
    parsed = read_results(path)
    assert parsed == rows


def test_from_dict_coerces_types() -> None:
    parsed = ArenaResult.from_dict(
        {
            "agent": "a",
            "scenario": "s",
            "seed": "42",  # string → int
            "population": 100,  # int → float
            "treasury_delta": -5_000,
            "renewable_share": "0.25",
            "raw_score": 1,
            "run_id": "rid",
            "submitted_at": 0,
        }
    )
    assert parsed.seed == 42
    assert isinstance(parsed.population, float)
    assert parsed.renewable_share == 0.25
