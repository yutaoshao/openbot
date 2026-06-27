from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.config import ModelProviderConfig
from src.infrastructure.providers.openai_responses import OpenAIResponsesProvider


class _FakeResponses:
    def __init__(self, response: SimpleNamespace) -> None:
        self._response = response
        self.requests: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.requests.append(kwargs)
        return self._response


def _make_provider(response: SimpleNamespace) -> OpenAIResponsesProvider:
    provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
    provider.config = ModelProviderConfig(
        provider="openai_responses",
        model="gpt-5.5",
        base_url="https://example.invalid/v1",
        max_tokens=2048,
        reasoning_effort="high",
        verbosity="low",
    )
    provider.model = "gpt-5.5"
    provider.client = SimpleNamespace(responses=_FakeResponses(response))
    return provider


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        input_tokens_details=SimpleNamespace(cached_tokens=64),
    )


def _message(*texts: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text) for text in texts],
    )


def _function_call(arguments: str = '{"path":"README.md"}') -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        id="item-1",
        call_id="call-1",
        name="read_file",
        arguments=arguments,
    )


async def test_chat_sends_responses_reasoning_request_and_maps_output() -> None:
    provider = _make_provider(
        SimpleNamespace(
            output=[
                _message("hello", " world"),
                _message("second line"),
                _function_call(),
            ],
            usage=_usage(),
        )
    )
    tools = [
        {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}], tools=tools)

    request = provider.client.responses.requests[0]
    assert request["model"] == "gpt-5.5"
    assert request["max_output_tokens"] == 2048
    assert request["reasoning"] == {"effort": "high"}
    assert request["text"] == {"verbosity": "low"}
    assert request["input"] == [{"role": "user", "content": "hi"}]
    assert request["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    assert "temperature" not in request
    assert response.text == "hello world\nsecond line"
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "README.md"}
    assert response.usage.tokens_in == 100
    assert response.usage.tokens_out == 20
    assert response.usage.cached_tokens == 64
    assert response.model == "gpt-5.5"


async def test_chat_rejects_invalid_tool_arguments() -> None:
    provider = _make_provider(
        SimpleNamespace(output=[_function_call("{not-json")], usage=None)
    )

    with pytest.raises(ValueError, match="Invalid JSON arguments for tool 'read_file'"):
        await provider.chat(messages=[])


async def test_chat_rejects_unsupported_output_type() -> None:
    provider = _make_provider(
        SimpleNamespace(output=[SimpleNamespace(type="web_search_call")], usage=None)
    )

    with pytest.raises(ValueError, match="Unsupported Responses output type: web_search_call"):
        await provider.chat(messages=[])


async def test_chat_stream_is_explicitly_unimplemented() -> None:
    provider = _make_provider(SimpleNamespace(output=[], usage=None))

    with pytest.raises(NotImplementedError, match="does not support streaming yet"):
        async for _ in provider.chat_stream(messages=[]):
            pass


def test_provider_requires_api_key_when_instantiated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_OPENAI_RESPONSES_KEY", raising=False)

    with pytest.raises(
        ValueError,
        match="Missing API key env MISSING_OPENAI_RESPONSES_KEY for openai_responses provider",
    ):
        OpenAIResponsesProvider(
            ModelProviderConfig(
                provider="openai_responses",
                model="gpt-5.5",
                base_url="https://example.invalid/v1",
                api_key_env="MISSING_OPENAI_RESPONSES_KEY",
            )
        )
