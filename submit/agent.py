"""Default participant submission.

`evaluate.py --agent submit.agent` resolves the symbol `Agent` here and
instantiates it as `Agent(api, seed=...)`.  The shipped default re-
exports `agents.scripted.ScriptedAgent` so a clean clone of the repo
can run `docker compose --profile eval run agent` and reproduce the
committed baseline score on seed 42.

Participants replace this file with their own agent.  The minimal
contract is: a class named `Agent` with `__init__(api, *, seed=None)`
and a `play_game(self) -> dict` method (see `agents/base.py`).
"""

from __future__ import annotations

from agents.scripted import ScriptedAgent as Agent

__all__ = ["Agent"]
