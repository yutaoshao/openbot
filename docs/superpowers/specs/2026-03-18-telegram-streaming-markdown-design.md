# Telegram Streaming Output & Markdown Rendering

**Date:** 2026-03-18
**Status:** Approved

## Overview

Add real-time streaming output and Markdown rendering for Telegram. Uses the
`sendMessageDraft` API (Bot API 9.5) for native draft-based streaming and HTML
parse mode for reliable Markdown display.

## Prerequisites

- Upgrade `python-telegram-bot` to `>=22.6` in `pyproject.toml` (current: `>=21.11`)
  - v22.6 added `Bot.send_message_draft()` (verified at runtime)

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Streaming mechanism | `sendMessageDraft` | Native draft UX, no "edited" label, smooth animation |
| Parse mode | HTML | More forgiving than MarkdownV2; handles partial content during streaming |
| Draft throttle | 0.5s (configurable) | Avoids Telegram rate limits (~30 msg/sec/chat) |
| Markdown converter | Custom lightweight parser | No heavy deps; handles Telegram HTML subset specifically |
| Non-streaming path | Preserved | `Agent.run()` delegates to `run_stream()` internally (DRY) |
| Metrics event | `agent.metrics` | Separate from `agent.response` to avoid MsgHub double-delivery |

## Data Model

### StreamChunk

New dataclass in `model_gateway.py`:

```python
@dataclass
class StreamChunk:
    type: Literal["text", "tool_call", "tool_status", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    tool_name: str = ""           # type="tool_status"
    usage: Usage | None = None    # type="done"
    model: str = ""               # type="done"
```

### StreamingAdapter Protocol

New protocol in `src/channels/types.py`:

```python
@runtime_checkable
class StreamingAdapter(Protocol):
    async def send_streaming(
        self, chat_id: str, stream: AsyncIterator[StreamChunk],
    ) -> None: ...
```

## Architecture

### Data Flow

```
User -> Telegram -> TelegramAdapter._on_message()
  -> MsgHub.handle_incoming() -> EventBus("msg.receive")
  -> Application._on_message_receive()
    -> Agent.run_stream() --- async generator ---+
      -> ModelGateway.chat_stream()              |
        -> Provider.chat_stream() (SSE)          |
          yield StreamChunk(text=...)  ----------+
          yield StreamChunk(tool_call=...) ------+ (agent executes, loops)
          yield StreamChunk(tool_status=...) ----+
          yield StreamChunk(done=...) -----------+
    -> TelegramAdapter.send_streaming()
      -> send_message_draft() x N (throttled)
      -> send_message() (final, HTML formatted)
  -> EventBus("agent.metrics") (metrics only, NOT "agent.response")
```

### Layer Changes

#### Layer 1: Provider -- chat_stream()

Both providers implement `chat_stream()` as an async generator:

**OpenAICompatibleProvider:**
- `client.chat.completions.create(stream=True, stream_options={"include_usage": True})`
- Parse SSE deltas: text delta -> `StreamChunk(type="text")`,
  tool_call chunks accumulated -> `StreamChunk(type="tool_call")`,
  stream end -> `StreamChunk(type="done", usage=...)`

**ClaudeProvider:**
- `client.messages.stream()`
- Parse content_block_delta events with same chunk type mapping.

**ModelGateway.chat_stream():**
- Same retry + fallback as `chat()`, but retry only at connection phase.
- Once streaming starts, errors propagate to caller (no mid-stream retry).

#### Layer 2: Agent -- run_stream()

```python
async def run_stream(
    self, input_text: str, conversation_id: str = "", platform: str = "unknown",
) -> AsyncIterator[StreamChunk]:
```

**DRY principle:** `run()` is refactored to internally consume `run_stream()`,
collecting all chunks and assembling the final `AgentResponse`. Both methods
share the same core logic. `run()` signature and return type remain unchanged
for backward compatibility.

All model calls use `chat_stream()`. Processing logic:

```
while iterations < max_iterations:
    async for chunk in model_gateway.chat_stream(messages, tools):
        if chunk.type == "text":
            yield chunk              # pass through to adapter
            accumulated_text += chunk.text
        elif chunk.type == "tool_call":
            collected_tool_calls.append(chunk.tool_call)
        elif chunk.type == "done":
            record usage

    if no tool_calls:
        break  # pure text response, streaming done

    # Tool calls: execute, yield status, continue loop
    for tc in collected_tool_calls:
        yield StreamChunk(type="tool_status", tool_name=tc.name)
        result = execute(tc)
        append to messages

    reset accumulated_text for next iteration
```

After loop: persist assistant message via ConversationManager, trigger
compression check, yield final `StreamChunk(type="done")`.

#### Layer 3: Application routing

`_on_message_receive()` checks adapter capability via Protocol:

```python
from src.channels.types import StreamingAdapter

adapter = self.msg_hub.get_adapter(message.platform)

if isinstance(adapter, StreamingAdapter):
    stream = self.agent.run_stream(...)
    await adapter.send_streaming(chat_id, stream)
    # Publish metrics-only event (MsgHub does NOT listen to this)
    await self.event_bus.publish("agent.metrics", {metrics...})
else:
    result = await self.agent.run(...)  # existing non-streaming path
    await self.event_bus.publish("agent.response", {...})  # MsgHub delivers
```

Key: streaming path publishes `"agent.metrics"` (not `"agent.response"`) so
MsgHub's `_on_agent_response` handler does not double-deliver the message.

`MsgHub` adds `get_adapter(platform)` to expose adapter references.

#### Layer 4: TelegramAdapter -- send_streaming()

```python
async def send_streaming(self, chat_id: str, stream: AsyncIterator[StreamChunk]) -> None:
    draft_id = random.randint(1, 2**31)
    accumulated = ""
    last_draft_time = 0.0
    consecutive_failures = 0
    MAX_DRAFT_FAILURES = 3

    async for chunk in stream:
        if chunk.type == "text":
            accumulated += chunk.text
            if time.monotonic() - last_draft_time >= self._stream_throttle:
                try:
                    html = md_to_telegram_html(accumulated, partial=True)
                    await bot.send_message_draft(
                        chat_id=int(chat_id), draft_id=draft_id,
                        text=html, parse_mode="HTML",
                    )
                    last_draft_time = time.monotonic()
                    consecutive_failures = 0
                except TelegramError:
                    consecutive_failures += 1
                    logger.warning("telegram.draft_failed", failures=consecutive_failures)
                    if consecutive_failures >= MAX_DRAFT_FAILURES:
                        # Fallback: send placeholder, switch to edit-based
                        break

        elif chunk.type == "tool_status":
            # Append status line to draft
            ...

        elif chunk.type == "done":
            collect metadata for metrics

    # Final message (Telegram client dismisses draft when real message arrives)
    final_html = md_to_telegram_html(accumulated, partial=False)
    await self._send_final_message(chat_id, final_html)
```

**Throttle:** Configurable via `TelegramConfig.stream_throttle` (default 0.5s).

**Error handling:**
- Draft failures: log warning, count consecutive failures.
- 3+ consecutive failures: degrade to fallback (send placeholder + edit, or
  just wait and send final message).
- Final `send_message` failure: raise exception (caller handles).

**Draft-to-message transition:** Per Telegram client behavior, sending a
regular `send_message` to the same chat dismisses any active draft bubble.
No explicit "clear draft" API call is needed.

**Long message splitting:** Final message respects 4096-char Telegram limit
via existing `_send_final_message()` chunking logic.

#### Layer 5: Markdown to Telegram HTML

New file: `src/channels/markdown.py`

```python
def md_to_telegram_html(text: str, partial: bool = False) -> str:
```

**Two-phase parsing:**

1. Block level (line-by-line): code fences, blockquotes, headers
2. Inline level (regex): bold, italic, strikethrough, inline code, links

**Conversion rules:**

| Markdown | Telegram HTML |
|----------|---------------|
| `**bold**` | `<b>bold</b>` |
| `*italic*` / `_italic_` | `<i>italic</i>` |
| `~~strike~~` | `<s>strike</s>` |
| `` `code` `` | `<code>code</code>` |
| ` ```lang ... ``` ` | `<pre><code class="language-lang">...</code></pre>` |
| `[text](url)` | `<a href="url">text</a>` |
| `> quote` | `<blockquote>quote</blockquote>` |
| `# Header` | `<b>Header</b>` |
| Lists (`-`/`1.`) | Preserved as-is |

**Streaming safety (`partial=True`):**
- Force-close unclosed code blocks / inline format tags
- On conversion failure, fallback to HTML-escaped plain text

**Security:**
- HTML-escape `<`, `>`, `&` in non-tag regions to prevent injection.
- Inside `<pre>` blocks, escape all HTML entities (no inline formatting).

## Config Change

```python
class TelegramConfig(BaseModel):
    # ... existing fields ...
    stream_throttle: float = 0.5  # seconds between draft updates
```

## File Change List

| File | Action | Content |
|------|--------|---------|
| `pyproject.toml` | Modify | `python-telegram-bot>=22.6` |
| `src/infrastructure/model_gateway.py` | Modify | `StreamChunk` dataclass, `ModelProvider.chat_stream()` protocol, `ModelGateway.chat_stream()` |
| `src/infrastructure/providers/openai_compat.py` | Modify | `OpenAICompatibleProvider.chat_stream()` |
| `src/infrastructure/providers/anthropic.py` | Modify | `ClaudeProvider.chat_stream()` |
| `src/agent/agent.py` | Modify | `run_stream()` async generator, `run()` refactored to consume `run_stream()` |
| `src/channels/types.py` | Modify | `StreamingAdapter` Protocol |
| `src/channels/markdown.py` | **New** | `md_to_telegram_html()` converter |
| `src/channels/adapters/telegram.py` | Modify | `send_streaming()`, draft throttling, fallback |
| `src/channels/hub.py` | Modify | `get_adapter()` method |
| `src/platform/config.py` | Modify | `TelegramConfig.stream_throttle` |
| `main.py` | Modify | `_on_message_receive()` streaming branch, `agent.metrics` event |

## Testing

### markdown.py unit tests
- Each Markdown syntax (bold, italic, code, links, headers, blockquotes, lists)
- Nested formatting (`**bold _italic_**`)
- Partial mode: unclosed code blocks, unclosed inline formatting
- HTML escaping: `<script>`, `&amp;`, user-injected tags
- Empty input, whitespace-only input
- Unicode content
- Long messages (>4096 chars)

### Provider chat_stream() tests
- Mock AsyncIterator: text-only stream, tool-call stream, mixed stream
- Usage/model extraction from "done" chunk
- Error mid-stream propagation

### Agent run_stream() tests
- Pure text response (no tool calls)
- Single tool call + text continuation
- Multiple sequential tool calls
- Max iterations reached during streaming
- Empty model response

### Integration (manual)
- Real Telegram bot: draft animation, final message display
- Long streaming response (>10s)
- Tool call status indicators during streaming
- Message >4096 chars splitting
