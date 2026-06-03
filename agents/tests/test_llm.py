"""Provider-abstraction unit tests for `agents.llm`.

Both `OpenAILLM` and `AnthropicLLM` are exercised with a stubbed httpx
client — we want to pin the wire-level request shape (so we don't drift
out of compatibility with either vendor) and the parsing of tool calls
back into the normalized `ToolCall` shape. Real network calls are HITL
verification, not AFK tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from agents.llm import (
    AnthropicLLM,
    LLMResponse,
    MockLLM,
    NimLLM,
    NvidiaLLM,
    OllamaLLM,
    OpenAILLM,
    ToolCall,
    Usage,
    make_llm_from_env,
)

# ---------- httpx stub ------------------------------------------------------


@dataclass
class _StubResponse:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


class _StubHTTPX:
    """Records POSTs and returns a queued response. Replaces httpx.Client
    on adapter instances during tests."""

    def __init__(self, response: _StubResponse) -> None:
        self.response = response
        self.last_url: str | None = None
        self.last_json: dict[str, Any] | None = None
        self.last_headers: dict[str, str] = {}

    def post(self, url: str, json: dict[str, Any] | None = None) -> _StubResponse:
        self.last_url = url
        self.last_json = json
        return self.response


def _toy_tool() -> dict[str, Any]:
    return {
        "name": "build",
        "description": "Place a tile.",
        "parameters": {
            "type": "object",
            "properties": {"tile_type": {"type": "string"}},
            "required": ["tile_type"],
        },
    }


# ---------- OpenAI adapter --------------------------------------------------


def test_openai_chat_sends_chat_completions_payload() -> None:
    """OpenAILLM POSTs to /chat/completions with the chat-completions schema."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_0",
                                    "type": "function",
                                    "function": {
                                        "name": "build",
                                        "arguments": json.dumps(
                                            {"tile_type": "house", "x": 4, "y": 5}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 18},
            },
        )
    )
    llm = OpenAILLM.__new__(OpenAILLM)  # bypass __init__ (which calls httpx)
    llm.model = "gpt-test"
    llm._client = stub
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()], max_tokens=128)

    assert stub.last_url == "/chat/completions"
    body = stub.last_json
    assert body is not None
    assert body["model"] == "gpt-test"
    assert body["max_tokens"] == 128
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "build"

    assert resp.tool_calls == [
        ToolCall(name="build", arguments={"tile_type": "house", "x": 4, "y": 5})
    ]
    assert resp.usage == Usage(input_tokens=120, output_tokens=18)
    assert resp.text == ""


def test_openai_chat_parses_string_arguments_safely() -> None:
    """Tool-call arguments arrive as JSON strings; a malformed string should
    yield an empty dict, not a parser crash."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "Plain reply",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "step",
                                        "arguments": "not-json-{",
                                    }
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )
    )
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.model = "x"
    llm._client = stub
    resp = llm.chat(system="", user="", tools=[])
    assert resp.tool_calls == [ToolCall(name="step", arguments={})]
    assert resp.text == "Plain reply"


def test_openai_chat_raises_on_http_error() -> None:
    """Non-2xx → RuntimeError surfaces the status + body."""
    stub = _StubHTTPX(_StubResponse(429, {}, text="rate limited"))
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.model = "x"
    llm._client = stub
    with pytest.raises(RuntimeError, match="OpenAI HTTP 429"):
        llm.chat(system="", user="", tools=[])


# ---------- Anthropic adapter -----------------------------------------------


def test_anthropic_chat_sends_messages_payload() -> None:
    """AnthropicLLM POSTs to /messages with system promoted out of the
    `messages` array (as a cache-controlled text block) and tools using
    `input_schema` (not `parameters`)."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "content": [
                    {"type": "text", "text": "thinking..."},
                    {
                        "type": "tool_use",
                        "id": "tu_0",
                        "name": "survey",
                        "input": {"x": 16, "y": 16, "size": 8},
                    },
                ],
                "usage": {"input_tokens": 200, "output_tokens": 24},
            },
        )
    )
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-test"
    llm._client = stub
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()], max_tokens=256)

    assert stub.last_url == "/messages"
    body = stub.last_json
    assert body is not None
    assert body["model"] == "claude-test"
    # System ships as a cache-controlled text block so Anthropic caches
    # the static prefix (tools + system) for ~5 minutes; subsequent /step
    # calls hit the cache instead of re-paying for the 7k-token prefix.
    assert body["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"] == [{"role": "user", "content": "usr"}]
    assert "input_schema" in body["tools"][0]
    assert "parameters" not in body["tools"][0]

    assert resp.tool_calls == [ToolCall(name="survey", arguments={"x": 16, "y": 16, "size": 8})]
    assert resp.text == "thinking..."
    assert resp.usage == Usage(input_tokens=200, output_tokens=24)


def test_anthropic_chat_records_prompt_cache_stats_in_usage() -> None:
    """Second-and-later /step calls hit the cache: Anthropic returns
    `cache_read_input_tokens` and the Usage dataclass surfaces it so
    the agent's cumulative-token counter can see how much was cached."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "content": [{"type": "text", "text": ""}],
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 12,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 7400,
                },
            },
        )
    )
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-test"
    llm._client = stub
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()])
    assert resp.usage.input_tokens == 80
    assert resp.usage.cache_read_input_tokens == 7400
    assert resp.usage.cache_creation_input_tokens == 0
    # `total` includes cache reads so the 1M-token budget stays
    # honest across cached and uncached calls.
    assert resp.usage.total == 80 + 12 + 7400


def test_anthropic_chat_raises_on_http_error() -> None:
    stub = _StubHTTPX(_StubResponse(401, {}, text="invalid key"))
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "x"
    llm._client = stub
    with pytest.raises(RuntimeError, match="Anthropic HTTP 401"):
        llm.chat(system="", user="", tools=[])


# ---------- Ollama adapter --------------------------------------------------


def test_ollama_chat_sends_api_chat_payload() -> None:
    """OllamaLLM POSTs /api/chat with OpenAI-shaped tools, stream=False,
    and num_predict carrying max_tokens. The response shape differs
    from OpenAI's: arguments arrive as a dict (not a JSON string) and
    usage lives in prompt_eval_count / eval_count at the top level."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "model": "gemma4",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "build",
                                "arguments": {"tile_type": "house", "x": 4, "y": 5},
                            }
                        }
                    ],
                },
                "prompt_eval_count": 67,
                "eval_count": 18,
            },
        )
    )
    llm = OllamaLLM.__new__(OllamaLLM)  # bypass __init__ (which calls httpx)
    llm.model = "gemma4"
    llm._client = stub
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()], max_tokens=128)

    assert stub.last_url == "/api/chat"
    body = stub.last_json
    assert body is not None
    assert body["model"] == "gemma4"
    assert body["stream"] is False
    assert body["options"] == {"num_predict": 128}
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "build"

    assert resp.tool_calls == [
        ToolCall(name="build", arguments={"tile_type": "house", "x": 4, "y": 5})
    ]
    assert resp.usage == Usage(input_tokens=67, output_tokens=18)
    assert resp.text == ""


def test_ollama_chat_accepts_string_arguments_from_forks() -> None:
    """Some Ollama-compatible forks pass `arguments` through as a JSON
    string (OpenAI-style). The adapter parses both shapes; malformed
    strings degrade to an empty dict rather than crashing."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "message": {
                    "content": "ok",
                    "tool_calls": [{"function": {"name": "step", "arguments": "not-json-{"}}],
                },
                "prompt_eval_count": 1,
                "eval_count": 2,
            },
        )
    )
    llm = OllamaLLM.__new__(OllamaLLM)
    llm.model = "gemma4"
    llm._client = stub
    resp = llm.chat(system="", user="", tools=[])
    assert resp.tool_calls == [ToolCall(name="step", arguments={})]
    assert resp.text == "ok"


def test_ollama_chat_raises_on_http_error() -> None:
    stub = _StubHTTPX(_StubResponse(500, {}, text="model not found"))
    llm = OllamaLLM.__new__(OllamaLLM)
    llm.model = "missing"
    llm._client = stub
    with pytest.raises(RuntimeError, match="Ollama HTTP 500"):
        llm.chat(system="", user="", tools=[])


# ---------- NIM adapter -----------------------------------------------------


def test_nim_chat_sends_chat_completions_payload_without_auth() -> None:
    """NimLLM POSTs /chat/completions with the OpenAI body shape and
    must NOT set an Authorization header — local NIM containers are
    unauthenticated, and the curl reference for a deployed NIM omits
    the header entirely."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "build",
                                        "arguments": json.dumps(
                                            {"tile_type": "solar_farm", "x": 3, "y": 7}
                                        ),
                                    }
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 140, "completion_tokens": 22},
            },
        )
    )
    llm = NimLLM.__new__(NimLLM)  # bypass __init__ (which calls httpx)
    llm.model = "openai/gpt-oss-120b"
    llm.chat_template_kwargs = None
    llm._client = stub
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()], max_tokens=512)

    assert stub.last_url == "/chat/completions"
    body = stub.last_json
    assert body is not None
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["max_tokens"] == 512
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "build"
    # The stub never receives a separate headers arg from .post(), so
    # any auth surface would have to leak through the body — verify
    # we didn't smuggle one in there either.
    assert "authorization" not in {k.lower() for k in body}

    assert resp.tool_calls == [
        ToolCall(name="build", arguments={"tile_type": "solar_farm", "x": 3, "y": 7})
    ]
    assert resp.usage == Usage(input_tokens=140, output_tokens=22)
    assert resp.text == ""


def test_nim_chat_accepts_dict_arguments_from_native_tool_callers() -> None:
    """Some NIM builds (and chat templates that pre-parse tool args)
    return `arguments` as a dict instead of a JSON string. The adapter
    accepts both shapes; malformed strings degrade to an empty dict."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "step",
                                        "arguments": {"days": 3},
                                    }
                                },
                                {
                                    "function": {
                                        "name": "build",
                                        "arguments": "not-json-{",
                                    }
                                },
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    llm = NimLLM.__new__(NimLLM)
    llm.model = "openai/gpt-oss-120b"
    llm.chat_template_kwargs = None
    llm._client = stub
    resp = llm.chat(system="", user="", tools=[])
    assert resp.tool_calls == [
        ToolCall(name="step", arguments={"days": 3}),
        ToolCall(name="build", arguments={}),
    ]
    assert resp.text == "ok"


def test_nim_chat_raises_on_http_error() -> None:
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [{"message": {"content": "ok", "tool_calls": []}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
    )
    llm = NimLLM.__new__(NimLLM)
    llm.model = "openai/gpt-oss-120b"
    llm.chat_template_kwargs = None
    llm._client = stub
    llm.chat(system="", user="", tools=[])
    # NIM rejects `"tools": []` with HTTP 400; the adapter must omit
    # the field rather than send it empty. The agent loop always
    # passes tools, but the smoke-test path (no tools) is load-bearing.
    body = stub.last_json
    assert body is not None
    assert "tools" not in body

    err_stub = _StubHTTPX(_StubResponse(503, {}, text="model not ready"))
    err_llm = NimLLM.__new__(NimLLM)
    err_llm.model = "openai/gpt-oss-120b"
    err_llm.chat_template_kwargs = None
    err_llm._client = err_stub
    with pytest.raises(RuntimeError, match="NIM HTTP 503"):
        err_llm.chat(system="", user="", tools=[{"name": "noop", "parameters": {}}])


# ---------- MockLLM ---------------------------------------------------------


def test_mock_llm_replays_responses_in_order() -> None:
    r1 = LLMResponse(tool_calls=[ToolCall("step", {"days": 1})], text="", usage=Usage(1, 1))
    r2 = LLMResponse(tool_calls=[ToolCall("step", {"days": 7})], text="", usage=Usage(2, 2))
    mock = MockLLM(responses=[r1, r2])
    a = mock.chat(system="s", user="u1", tools=[])
    b = mock.chat(system="s", user="u2", tools=[])
    assert a is r1 and b is r2
    assert len(mock.calls) == 2
    assert mock.calls[0]["user"] == "u1"


def test_mock_llm_repeats_final_response_when_drained() -> None:
    r = LLMResponse(tool_calls=[ToolCall("step", {"days": 7})], text="", usage=Usage(0, 0))
    mock = MockLLM(responses=[r])
    a = mock.chat(system="", user="", tools=[])
    b = mock.chat(system="", user="", tools=[])
    assert a is r and b is r


def test_mock_llm_empty_returns_empty_response() -> None:
    mock = MockLLM(responses=[])
    resp = mock.chat(system="", user="", tools=[])
    assert resp.tool_calls == []
    assert resp.usage.total == 0


# ---------- Factory ---------------------------------------------------------


def test_make_llm_from_env_requires_api_key() -> None:
    """The default (openai) provider reads its own namespaced key."""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        make_llm_from_env(env={})


def test_make_llm_from_env_defaults_to_openai() -> None:
    llm = make_llm_from_env(env={"OPENAI_API_KEY": "k"})
    assert isinstance(llm, OpenAILLM)
    assert llm.model == "gpt-4o-mini"


def test_make_llm_from_env_selects_anthropic() -> None:
    llm = make_llm_from_env(
        env={"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "claude-x"}
    )
    assert isinstance(llm, AnthropicLLM)
    assert llm.model == "claude-x"


def test_make_llm_from_env_anthropic_requires_anthropic_api_key() -> None:
    """Each provider reads only its own namespace — an OPENAI_API_KEY in
    the environment must not satisfy the anthropic branch."""
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        make_llm_from_env(env={"LLM_PROVIDER": "anthropic", "OPENAI_API_KEY": "k"})


def test_make_llm_from_env_rejects_unknown_provider() -> None:
    with pytest.raises(RuntimeError, match="unknown LLM_PROVIDER"):
        make_llm_from_env(env={"LLM_PROVIDER": "google"})


def test_make_llm_from_env_selects_ollama_without_api_key() -> None:
    """Ollama runs locally and unauthenticated; the factory must not
    demand an API key for it, and must default the model to gemma4."""
    llm = make_llm_from_env(env={"LLM_PROVIDER": "ollama"})
    assert isinstance(llm, OllamaLLM)
    assert llm.model == "gemma4"


def test_make_llm_from_env_ollama_respects_model_override() -> None:
    llm = make_llm_from_env(env={"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3.2"})
    assert isinstance(llm, OllamaLLM)
    assert llm.model == "llama3.2"


# ---------- Factory: NIM branch ---------------------------------------------


def test_make_llm_from_env_selects_nim_without_api_key() -> None:
    """NIM containers are unauthenticated; the factory must not demand
    an API key for them, and must default the model to gpt-oss-120b."""
    llm = make_llm_from_env(env={"LLM_PROVIDER": "nim", "NIM_BASE_URL": "http://localhost:8000/v1"})
    assert isinstance(llm, NimLLM)
    assert llm.model == "openai/gpt-oss-120b"


def test_make_llm_from_env_nim_reads_nim_base_url() -> None:
    """NIM_BASE_URL is the endpoint; it flows into the httpx client.
    NimLLM strips the trailing slash before handing it to httpx; httpx
    then normalises back to a trailing-slash form internally — assert
    the host+path match, ignoring the canonicalisation."""
    llm = make_llm_from_env(
        env={"LLM_PROVIDER": "nim", "NIM_BASE_URL": "http://34.124.237.72:8000/v1"}
    )
    assert isinstance(llm, NimLLM)
    assert str(llm._client.base_url).rstrip("/") == "http://34.124.237.72:8000/v1"


def test_make_llm_from_env_nim_requires_base_url() -> None:
    """No HTTP attempt either — the missing-base-url branch fires before
    we ever try to construct the httpx client."""
    with pytest.raises(RuntimeError, match="NIM_BASE_URL"):
        make_llm_from_env(env={"LLM_PROVIDER": "nim"})


def test_make_llm_from_env_nim_forwards_chat_template_kwargs() -> None:
    """`NIM_CHAT_TEMPLATE_KWARGS` is a JSON object forwarded to vLLM
    per-request. The load-bearing case is `{"enable_thinking": false}`
    for Nemotron-3 family NIMs — without it, the model burns ~10x the
    output tokens on chain-of-thought the agent loop ignores."""
    llm = make_llm_from_env(
        env={
            "LLM_PROVIDER": "nim",
            "NIM_BASE_URL": "http://localhost:8000/v1",
            "NIM_CHAT_TEMPLATE_KWARGS": '{"enable_thinking": false}',
        }
    )
    assert isinstance(llm, NimLLM)
    assert llm.chat_template_kwargs == {"enable_thinking": False}


def test_make_llm_from_env_nim_rejects_malformed_chat_template_kwargs() -> None:
    """A typo'd JSON value here would silently leave thinking on (since
    vLLM ignores unknown kwargs), so the factory bails loudly instead."""
    with pytest.raises(RuntimeError, match="NIM_CHAT_TEMPLATE_KWARGS"):
        make_llm_from_env(
            env={
                "LLM_PROVIDER": "nim",
                "NIM_BASE_URL": "http://localhost:8000/v1",
                "NIM_CHAT_TEMPLATE_KWARGS": "{not-json",
            }
        )
    with pytest.raises(RuntimeError, match="JSON object"):
        make_llm_from_env(
            env={
                "LLM_PROVIDER": "nim",
                "NIM_BASE_URL": "http://localhost:8000/v1",
                "NIM_CHAT_TEMPLATE_KWARGS": "[1, 2, 3]",
            }
        )


def test_nim_chat_forwards_chat_template_kwargs_in_body() -> None:
    """When the adapter is constructed with chat_template_kwargs, every
    chat() body must include that field — otherwise Nemotron-3 NIMs
    would silently ignore the thinking-off directive."""
    stub = _StubHTTPX(
        _StubResponse(
            200,
            {
                "choices": [{"message": {"content": "ok", "tool_calls": []}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
    )
    llm = NimLLM.__new__(NimLLM)
    llm.model = "nvidia/nemotron-3-super-120b-a12b"
    llm.chat_template_kwargs = {"enable_thinking": False}
    llm._client = stub
    llm.chat(system="", user="", tools=[{"name": "noop", "parameters": {}}])
    body = stub.last_json
    assert body is not None
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_make_llm_from_env_nim_respects_model_override() -> None:
    llm = make_llm_from_env(
        env={
            "LLM_PROVIDER": "nim",
            "NIM_BASE_URL": "http://localhost:8000/v1",
            "NIM_MODEL": "meta/llama-3.3-70b-instruct",
        }
    )
    assert isinstance(llm, NimLLM)
    assert llm.model == "meta/llama-3.3-70b-instruct"


# ---------- NVIDIA adapter --------------------------------------------------


@dataclass
class _FakeAIMessage:
    """Minimal AIMessage shape consumed by NvidiaLLM.chat — just the
    three attributes the adapter reads, no langchain_core dependency
    in the test fixtures themselves."""

    content: str
    tool_calls: list[dict[str, Any]]
    usage_metadata: dict[str, int]


class _FakeChatNVIDIA:
    """Stand-in for `langchain_nvidia_ai_endpoints.ChatNVIDIA` that
    records `bind_tools` and `bind` calls and returns a canned
    `AIMessage` on `invoke`. The adapter only relies on the Runnable
    contract (`bind_tools → Runnable`, `bind → Runnable`, `invoke →
    AIMessage`), so we don't need real langchain plumbing here."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        ai_message: _FakeAIMessage | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.bound_tools: list[Any] | None = None
        self.bound_kwargs: dict[str, Any] = {}
        self.invoked_messages: list[Any] | None = None
        self._ai_message = ai_message or _FakeAIMessage("", [], {})

    def bind_tools(self, tools: list[Any]) -> _FakeChatNVIDIA:
        self.bound_tools = tools
        return self

    def bind(self, **kwargs: Any) -> _FakeChatNVIDIA:
        self.bound_kwargs.update(kwargs)
        return self

    def invoke(self, messages: list[Any]) -> _FakeAIMessage:
        self.invoked_messages = messages
        return self._ai_message


def _install_fake_chat_nvidia(
    monkeypatch: pytest.MonkeyPatch, ai_message: _FakeAIMessage | None = None
) -> dict[str, Any]:
    """Replace `langchain_nvidia_ai_endpoints.ChatNVIDIA` with a stub
    factory so NvidiaLLM.__init__ doesn't try to hit NVIDIA at test
    time. Returns a dict the test can read to assert constructor args."""
    captured: dict[str, Any] = {}

    def _factory(*, model: str, api_key: str, base_url: str | None = None) -> _FakeChatNVIDIA:
        captured["model"] = model
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        client = _FakeChatNVIDIA(
            model=model, api_key=api_key, base_url=base_url, ai_message=ai_message
        )
        captured["client"] = client
        return client

    monkeypatch.setattr("langchain_nvidia_ai_endpoints.ChatNVIDIA", _factory)
    return captured


def test_nvidia_llm_translates_ai_message_into_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LangChain returns AIMessage with pre-parsed tool_calls and
    LangChain-shaped usage_metadata. NvidiaLLM must normalize both
    into the same `LLMResponse` the agent loop consumes from every
    other adapter."""
    ai = _FakeAIMessage(
        content="solar it is.",
        tool_calls=[
            {
                "name": "build",
                "args": {"tile_type": "solar", "x": 3, "y": 7},
                "id": "tool_0",
                "type": "tool_call",
            }
        ],
        usage_metadata={"input_tokens": 200, "output_tokens": 24, "total_tokens": 224},
    )
    captured = _install_fake_chat_nvidia(monkeypatch, ai_message=ai)

    llm = NvidiaLLM(api_key="nvapi-test", model="moonshotai/kimi-k2.6")
    resp = llm.chat(system="sys", user="usr", tools=[_toy_tool()], max_tokens=512)

    # Constructor passed through to ChatNVIDIA verbatim, with the NIM
    # endpoint as the default base URL.
    assert captured["model"] == "moonshotai/kimi-k2.6"
    assert captured["api_key"] == "nvapi-test"
    assert captured["base_url"] == NvidiaLLM.DEFAULT_BASE_URL

    # bind_tools sees the OpenAI-shaped tool schema (NVIDIA / LangChain
    # both consume that shape directly).
    client = captured["client"]
    assert client.bound_tools is not None and len(client.bound_tools) == 1
    assert client.bound_tools[0]["type"] == "function"
    assert client.bound_tools[0]["function"]["name"] == "build"

    # max_completion_tokens flows through .bind() to the underlying call.
    assert client.bound_kwargs == {"max_completion_tokens": 512}

    # Two messages dispatched: SystemMessage(content=sys), HumanMessage(content=usr).
    msgs = client.invoked_messages
    assert msgs is not None and len(msgs) == 2
    assert msgs[0].content == "sys"
    assert msgs[1].content == "usr"

    # Tool calls normalize to ToolCall(name, arguments=dict).
    assert resp.tool_calls == [
        ToolCall(name="build", arguments={"tile_type": "solar", "x": 3, "y": 7})
    ]
    assert resp.text == "solar it is."
    assert resp.usage == Usage(input_tokens=200, output_tokens=24)


def test_nvidia_llm_handles_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model with no tool capability returns an AIMessage with no
    tool_calls and possibly missing usage_metadata. The adapter must
    not crash on either."""
    ai = _FakeAIMessage(content="just text", tool_calls=[], usage_metadata={})
    _install_fake_chat_nvidia(monkeypatch, ai_message=ai)
    llm = NvidiaLLM(api_key="k", model="moonshotai/kimi-k2.6")
    resp = llm.chat(system="", user="", tools=[])
    assert resp.tool_calls == []
    assert resp.text == "just text"
    assert resp.usage == Usage(input_tokens=0, output_tokens=0)


def test_nvidia_llm_skips_bind_tools_when_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling `bind_tools([])` raises on some langchain versions; we
    only bind when the caller actually passes tools."""
    _install_fake_chat_nvidia(monkeypatch, ai_message=_FakeAIMessage("ok", [], {}))
    llm = NvidiaLLM(api_key="k", model="moonshotai/kimi-k2.6")
    llm.chat(system="", user="", tools=[])
    assert llm._client.bound_tools is None  # bind_tools was never called


# ---------- Factory: NVIDIA branch ------------------------------------------


def test_make_llm_from_env_nvidia_builds_nvidia_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory routes LLM_PROVIDER=nvidia to NvidiaLLM (ChatNVIDIA-
    backed), with moonshotai/kimi-k2.6 as the default model."""
    captured = _install_fake_chat_nvidia(monkeypatch)
    llm = make_llm_from_env(env={"LLM_PROVIDER": "nvidia", "NVIDIA_API_KEY": "k"})
    assert isinstance(llm, NvidiaLLM)
    assert llm.model == "moonshotai/kimi-k2.6"
    assert captured["base_url"] == NvidiaLLM.DEFAULT_BASE_URL


def test_make_llm_from_env_nvidia_requires_api_key() -> None:
    """No HTTP attempt either — the missing-key branch fires before we
    ever try to construct ChatNVIDIA. Each provider reads only its own
    namespace, so an OPENAI_API_KEY must not satisfy nvidia."""
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        make_llm_from_env(env={"LLM_PROVIDER": "nvidia", "OPENAI_API_KEY": "k"})


def test_make_llm_from_env_nvidia_respects_base_url_and_model_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private NIM deployments live at custom URLs; NVIDIA_BASE_URL +
    NVIDIA_MODEL flow through to ChatNVIDIA."""
    captured = _install_fake_chat_nvidia(monkeypatch)
    llm = make_llm_from_env(
        env={
            "LLM_PROVIDER": "nvidia",
            "NVIDIA_API_KEY": "k",
            "NVIDIA_BASE_URL": "https://nim.internal/v1",
            "NVIDIA_MODEL": "meta/llama-3.3-70b-instruct",
        }
    )
    assert isinstance(llm, NvidiaLLM)
    assert llm.model == "meta/llama-3.3-70b-instruct"
    assert captured["base_url"] == "https://nim.internal/v1"
