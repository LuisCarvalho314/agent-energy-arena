"""Arena package — `(agent, scenario)` runner.

Two modules:

- `arena.results`: `ArenaResult` dataclass + JSON I/O for the per-pair
  result schema (population, treasury delta, renewable share, raw
  score, run folder id, submission timestamp). Each run is independent;
  external tooling consumes the JSON rows to track agents over time.
- `arena.runner`: orchestrates `(agent, scenario)` pairs as
  subprocesses for isolation; each pair shells out to
  `python evaluate.py --agent <A> --scenario <S> --seed <Z>` and
  captures the JSON line into an `ArenaResult`. CLI:
  `python -m arena.runner`.
"""
