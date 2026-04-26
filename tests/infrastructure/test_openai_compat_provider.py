from __future__ import annotations

from types import SimpleNamespace

from src.core.config import ModelProviderConfig
from src.infrastructure.providers.openai_compat import OpenAICompatibleProvider


class _FakeStream:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


class _FakeCompletions:
    def __init__(
        self,
        events: list[SimpleNamespace],
        response: SimpleNamespace | None,
    ) -> None:
        self._events = events
        self._response = response

    async def create(self, **kwargs: object) -> _FakeStream | SimpleNamespace:
        if kwargs.get("stream"):
            return _FakeStream(self._events)
        if self._response is None:
            raise AssertionError("chat response was not configured")
        return self._response


def _make_chat_response(usage: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello", tool_calls=None),
            )
        ],
        usage=usage,
    )


def _make_usage(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
    )


def _make_stream_usage_event(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        usage=_make_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        ),
        choices=[],
    )


def _make_provider(
    events: list[SimpleNamespace] | None = None,
    response: SimpleNamespace | None = None,
) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.config = ModelProviderConfig(
        provider="openai_compatible",
        model="test-model",
        base_url="https://example.invalid/v1",
    )
    provider.model = "test-model"
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=_FakeCompletions(events or [], response),
        )
    )
    return provider


async def test_chat_reports_cached_prompt_tokens() -> None:
    provider = _make_provider(
        response=_make_chat_response(
            _make_usage(prompt_tokens=100, completion_tokens=20, cached_tokens=64)
        )
    )

    response = await provider.chat(messages=[])

    assert response.usage.tokens_in == 100
    assert response.usage.tokens_out == 20
    assert response.usage.cached_tokens == 64
    assert response.usage.cache_hit_ratio == 0.64


async def test_chat_stream_reports_cached_prompt_tokens() -> None:
    provider = _make_provider(
        events=[
            _make_stream_usage_event(
                prompt_tokens=200,
                completion_tokens=30,
                cached_tokens=128,
            )
        ]
    )

    chunks = [chunk async for chunk in provider.chat_stream(messages=[])]

    assert chunks[-1].usage is not None
    assert chunks[-1].usage.cached_tokens == 128
    assert chunks[-1].usage.cache_hit_ratio == 0.64


class _LegacyFakeCompletions:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    async def create(self, **_: object) -> _FakeStream:
        return _FakeStream(self._events)


def _make_legacy_provider(events: list[SimpleNamespace]) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.config = ModelProviderConfig(
        provider="openai_compatible",
        model="test-model",
        base_url="https://example.invalid/v1",
    )
    provider.model = "test-model"
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=_LegacyFakeCompletions(events),
        )
    )
    return provider


def _stream_event(
    *,
    tool_name: str | None = None,
    tool_arguments: str | None = None,
    tool_call_id: str | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    tool_calls = None
    if tool_name is not None or tool_arguments is not None or tool_call_id is not None:
        tool_calls = [
            SimpleNamespace(
                index=0,
                id=tool_call_id,
                function=SimpleNamespace(
                    name=tool_name,
                    arguments=tool_arguments,
                ),
            )
        ]
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
    )


async def test_chat_stream_deduplicates_repeated_tool_name_deltas() -> None:
    provider = _make_legacy_provider(
        [
            _stream_event(tool_name="web_fetch", tool_call_id="call-1"),
            _stream_event(
                tool_name="web_fetch",
                tool_arguments='{"url":"https://example.com"}',
                finish_reason="tool_calls",
            ),
        ]
    )

    chunks = [chunk async for chunk in provider.chat_stream(messages=[])]

    tool_chunks = [chunk for chunk in chunks if chunk.type == "tool_call"]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].tool_call is not None
    assert tool_chunks[0].tool_call.name == "web_fetch"
