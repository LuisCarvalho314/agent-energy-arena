"""LangGraph reference agent (5-node graph with rule-based critic).

The agent class lives in `agent.py` so the Agent Play attach handler
(`world.api.post_agent_attach`) can load this folder by path. This
package's namespace re-exports the class (and `RULES`) so existing
call sites (`from agents.langgraph_agent import LangGraphAgent`) keep
working unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["Agent", "LangGraphAgent", "RULES"]

if TYPE_CHECKING:
    from agents.llm_supervisor.agent import RULES, Agent, LangGraphAgent


def __getattr__(name: str):
    if name in __all__:
        from agents.llm_supervisor import agent

        return getattr(agent, name)
    raise AttributeError(name)
