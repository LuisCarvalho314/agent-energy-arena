"""Live integration test for a self-hosted NIM container.

NIM containers expose `/v1/chat/completions` with the OpenAI wire
format (no auth on a vanilla deployment). This test exercises the
adapter end-to-end against whatever endpoint `NIM_BASE_URL` points at.
The canonical curl reference used to validate the deployment:

    curl -X POST '$NIM_BASE_URL/chat/completions' \
      -H 'Content-Type: application/json' \
      -d '{"model": "openai/gpt-oss-120b",
           "messages": [{"role": "user", "content": "ping"}],
           "max_tokens": 64}'

Skipped automatically when `NIM_BASE_URL` is not in the environment
(or in `.env`). Always tagged `@pytest.mark.live` so `make check`
(which runs with `-m 'not live'`) skips it. Opt in with
`pytest -m live`.

Override the default model with `NIM_TEST_MODEL=...` when the deployed
NIM serves something other than `openai/gpt-oss-120b`.

Failure modes worth reading by hand:
  * `404 Not Found` on `/v1/chat/completions` — `NIM_BASE_URL` is
    pointing at the host root; it must include the `/v1` suffix.
  * `400 tools must not be an empty array` — pre-fix regression; the
    adapter now omits the field when empty.
  * Test passes but `tool_calls` is empty even when the model's
    `reasoning` channel describes calling a tool — the deployment's
    inference backend (vLLM, TensorRT-LLM, …) is not configured with
    the right tool-call parser for the served model. For gpt-oss-*
    served via vLLM, that typically means launching with
    `--tool-call-parser=harmony` (see `test_nim_tool_calls_are_parsed`
    for the diagnostic).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load `.env` from the repo root so a `NIM_BASE_URL=http://host:port/v1`
# line there is picked up without exporting it in every shell.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

pytestmark = [
    # Excluded from `make check` by the `-m 'not live'` filter in
    # pyproject. Opt in explicitly with `pytest -m live`.
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("NIM_BASE_URL"),
        reason="NIM_BASE_URL not set — live NIM test skipped",
    ),
]


def _build_llm() -> object:
    from agents.llm import make_llm_from_env

    return make_llm_from_env(
        env={
            "LLM_PROVIDER": "nim",
            "NIM_BASE_URL": os.environ["NIM_BASE_URL"],
            "LLM_MODEL": os.environ.get("NIM_TEST_MODEL", "openai/gpt-oss-120b"),
        }
    )


def test_nim_chat_returns_some_text() -> None:
    """End-to-end: build the adapter from env and verify the deployed
    NIM answers a plain user prompt.

    Asserts that we received non-empty content back and that the
    container reported token usage. Output wording is non-deterministic
    so we only check non-emptiness — a silent empty-response failure
    is what we want this test to flag.
    """
    from agents.llm import NimLLM

    llm = _build_llm()
    assert isinstance(llm, NimLLM)
    resp = llm.chat(
        system="You are a terse assistant.",
        user="Say 'pong'.",
        tools=[],
        max_tokens=64,
    )
    assert resp.text, (
        "NIM returned an empty content string — likely a model-routing "
        "or max_tokens issue on the deployed container."
    )
    # Usage is best-effort across vLLM/TensorRT-LLM backends; require
    # only that something non-zero came back so a backend that silently
    # drops the `usage` block fails loud here rather than corrupting
    # the agent's 1M-token budget counter at runtime.
    assert resp.usage.total > 0, "NIM did not report token usage"


def test_nim_tool_calls_are_parsed() -> None:
    """The agent loop is built around tool calling; a NIM that doesn't
    surface `tool_calls` in the response shape is unusable as an LLM
    backend for this project. This test proves the deployment's tool-
    call parser is wired up correctly.

    Most failure modes here are deployment-side, not adapter-side: the
    served model's chat template, the inference backend's tool-call
    parser flag, and the way the container exposes tool output all
    have to agree. For gpt-oss-* on vLLM, that typically means launching
    with `--tool-call-parser=harmony` (or the equivalent for the
    serving stack in use).
    """
    llm = _build_llm()
    resp = llm.chat(  # type: ignore[attr-defined]
        system=(
            "You drive a simulator by emitting tool calls. The only "
            "valid action is `step(days=N)` with N in [1, 7]. Emit "
            "exactly one tool call and no prose."
        ),
        user="Advance the simulation by 3 days.",
        tools=[
            {
                "name": "step",
                "description": "Advance the simulation by `days` days.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "minimum": 1, "maximum": 7},
                    },
                    "required": ["days"],
                },
            }
        ],
        max_tokens=128,
    )
    assert resp.tool_calls, (
        "NIM returned no tool_calls despite a single-tool schema and a "
        "prompt that maps cleanly onto it. This is almost always a "
        "deployment-side issue: the inference backend is not parsing "
        "the model's tool-call emission into the OpenAI tool_calls "
        "array. For gpt-oss-* on vLLM, relaunch the container with "
        "`--tool-call-parser=harmony`."
    )
    assert resp.tool_calls[0].name == "step"
