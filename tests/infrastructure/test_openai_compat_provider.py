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
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    async def create(self, **_: object) -> _FakeStream:
        return _FakeStream(self._events)


def _make_provider(events: list[SimpleNamespace]) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.config = ModelProviderConfig(
        provider="openai_compatible",
        model="test-model",
        base_url="https://example.invalid/v1",
    )
    provider.model = "test-model"
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=_FakeCompletions(events),
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
    provider = _make_provider(
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
