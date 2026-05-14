# Context

Project glossary. New terms are added here lazily as design decisions name them — see the `/improve-codebase-architecture` and `/grill-with-docs` skills.

Title-case in this file is load-bearing: it means "the specific concept defined below," not the colloquial English word. RULES.md, README.md, and agent docs use lowercase prose; this file is where the typed vocabulary lives.

## Vocabulary

### Action

A frozen-dataclass ADT in `world/action.py` representing one of the nine mutating commands an agent or evaluator issues against a World:

`Build | Demolish | Survey | Drill | ControlWell | ControlBattery | ControlRefinery | Reset | Scenario`

Each variant carries its params verbatim and is byte-equivalent to a single line in `actions.jsonl` (via `to_log_entry()` / `from_log_entry()`). Replay reconstructs an Action from its log entry and re-executes; the `result` field in the log is forensic, not load-bearing.

Not to be confused with the lowercase "action" used in `RULES.md`, `README.md`, and `agents/scripted.py`, which is the colloquial sense — "what an agent does in a turn." Every title-case Action is a lowercase action, but not vice versa: `step` is a lowercase action (the tick verb) and is deliberately **not** a title-case Action — its result shape (`{day_completed, summary, ...}`) doesn't fit the [[ActionResult]] envelope and the day-loop is its own seam.

### ActionResult

A frozen-dataclass envelope `{ok: bool, error: str | None, treasury_after: float, result: dict | None}` returned by the [[executor]] for every [[Action]]. Replaces the ad-hoc dicts the `World` methods return today — same shape, given a name.

### executor

The single entry point in `world/executor.py` — `execute(world, action_log, action) → ActionResult`. Owns the `(Action → World mutation → action_log entry → ActionResult)` pipeline. The seam through which all cross-cutting concerns ride: log writes, replay reconstruction via `Action.from_log_entry`, and (out-of-scope, but the signature has room) future dry-run, batch, metrics.

Concretely: an `executor.execute` call pattern-matches on the [[Action]] variant, delegates to the existing `World.build / demolish / survey / drill / control_* / reset / scenario` methods unchanged, calls `action_log.append(...)`, and returns the [[ActionResult]].
