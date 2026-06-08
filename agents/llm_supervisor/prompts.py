"""Prompting for the coordinate-free LLM supervisor.

The supervisor does not ask the model to choose map coordinates or drill
targets. The model chooses intent; deterministic action code maps that
intent onto concrete API calls from the current world state.
"""

from __future__ import annotations

SUPERVISOR_SYSTEM_PROMPT: str = """\
Choose intent-level actions for a city-energy sim. Optimize solvency,
population, happiness, renewable share, and survival.

Never choose coordinates or drill x/y/z; deterministic code chooses them
from state. Use needs/recommended_intents. Tool calls only: 1-3 useful
actions, then step(days=1..7).
"""
