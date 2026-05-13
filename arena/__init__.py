"""Arena package — `(agent, scenario)` runner + leaderboard.

Three modules:

- `arena.results`: `ArenaResult` dataclass + JSON I/O for the per-pair
  result schema (population, treasury delta, renewable share, raw
  score, run folder id, submission timestamp).
- `arena.runner`: orchestrates `(agent, scenario)` pairs as
  subprocesses for isolation; each pair shells out to
  `python evaluate.py --agent <A> --scenario <S> --seed <Z>` and
  captures the JSON line into an `ArenaResult`. CLI:
  `python -m arena.runner`.
- `arena.leaderboard`: pure-function aggregator. Takes a list of
  `ArenaResult`s, ranks agents per-scenario by raw score, and produces
  a Markdown ranked table via mean-rank across scenarios. Ties break
  on mean raw score, then submission timestamp.
"""
