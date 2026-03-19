"""Markdown to Telegram HTML converter.

Converts standard Markdown to the HTML subset supported by Telegram Bot API.
Designed for both complete and partial (streaming) content.

Supported Telegram HTML tags:
  <b>, <i>, <s>, <code>, <pre>, <a>, <blockquote>
"""

from __future__ import annotations

import re
from html import escape as html_escape


def md_to_telegram_html(text: str, *, partial: bool = False) -> str:
    """Convert Markdown text to Telegram-compatible HTML.

    Args:
        text: Standard Markdown text.
        partial: If True, force-close unclosed formatting tags (for
            streaming draft updates). On conversion failure, falls back
            to HTML-escaped plain text.

    Returns:
        HTML string safe for Telegram ``parse_mode="HTML"``.
    """
    if not text:
        return ""

    try:
        result = _convert(text, partial=partial)
    except Exception:
        # Fallback: return HTML-escaped plain text
        result = html_escape(text)

    return result


# ---------------------------------------------------------------------------
# Internal conversion
# ---------------------------------------------------------------------------

# Code fence pattern:  ```lang\n...\n```
_CODE_FENCE_OPEN = re.compile(r"^```(\w*)\s*$")
_CODE_FENCE_CLOSE = re.compile(r"^```\s*$")

# Blockquote prefix
_BLOCKQUOTE_PREFIX = re.compile(r"^>\s?(.*)")

# Header pattern
_HEADER = re.compile(r"^(#{1,6})\s+(.*)")


def _convert(text: str, *, partial: bool) -> str:
    lines = text.split("\n")
    output: list[str] = []

    in_code_block = False
    code_lang = ""
    code_lines: list[str] = []
    blockquote_lines: list[str] = []

    for line in lines:
        # --- Code fence handling ---
        if not in_code_block:
            m = _CODE_FENCE_OPEN.match(line)
            if m:
                # Flush any pending blockquote
                _flush_blockquote(blockquote_lines, output)
                in_code_block = True
                code_lang = m.group(1)
                code_lines = []
                continue
        else:
            if _CODE_FENCE_CLOSE.match(line):
                _flush_code_block(code_lang, code_lines, output)
                in_code_block = False
                code_lang = ""
                code_lines = []
                continue
            code_lines.append(line)
            continue

        # --- Blockquote handling ---
        bq = _BLOCKQUOTE_PREFIX.match(line)
        if bq:
            blockquote_lines.append(bq.group(1))
            continue

        # Flush blockquote if we exit it
        _flush_blockquote(blockquote_lines, output)

        # --- Header handling ---
        hm = _HEADER.match(line)
        if hm:
            content = _convert_inline(html_escape(hm.group(2)))
            output.append(f"<b>{content}</b>")
            continue

        # --- Regular line: inline formatting ---
        output.append(_convert_inline(html_escape(line)))

    # Flush remaining blocks
    _flush_blockquote(blockquote_lines, output)

    if in_code_block:
        if partial:
            # Force-close unclosed code block
            _flush_code_block(code_lang, code_lines, output)
        else:
            # Treat as regular text
            prefix = f"```{code_lang}" if code_lang else "```"
            output.append(html_escape(prefix))
            for cl in code_lines:
                output.append(html_escape(cl))

    result = "\n".join(output)

    if partial:
        result = _force_close_inline(result)

    return result


def _flush_code_block(
    lang: str, lines: list[str], output: list[str],
) -> None:
    """Render a code block as <pre><code>...</code></pre>."""
    escaped = html_escape("\n".join(lines))
    if lang:
        output.append(
            f'<pre><code class="language-{html_escape(lang)}">'
            f"{escaped}</code></pre>"
        )
    else:
        output.append(f"<pre><code>{escaped}</code></pre>")


def _flush_blockquote(lines: list[str], output: list[str]) -> None:
    """Render accumulated blockquote lines."""
    if not lines:
        return
    content = "\n".join(_convert_inline(html_escape(quote_line)) for quote_line in lines)
    output.append(f"<blockquote>{content}</blockquote>")
    lines.clear()


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------

# Order matters: process code first (to protect its content), then others.
# Inline code: `code`
_INLINE_CODE = re.compile(r"`([^`]+)`")
# Bold: **text**
_BOLD = re.compile(r"\*\*(.+?)\*\*")
# Italic: *text*  (but not **)
_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
# Italic: _text_  (word boundary aware)
_ITALIC_UNDER = re.compile(r"(?<!\w)_([^_]+?)_(?!\w)")
# Strikethrough: ~~text~~
_STRIKE = re.compile(r"~~(.+?)~~")
# Link: [text](url)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Placeholder to protect inline code from further processing
_CODE_PLACEHOLDER = "\x00CODE{}\x00"


def _convert_inline(text: str) -> str:
    """Apply inline Markdown formatting to a single line.

    Input text must already be HTML-escaped.
    """
    # Extract inline code spans first to protect them
    code_spans: list[str] = []

    def _save_code(m: re.Match) -> str:
        idx = len(code_spans)
        code_spans.append(f"<code>{m.group(1)}</code>")
        return _CODE_PLACEHOLDER.format(idx)

    text = _INLINE_CODE.sub(_save_code, text)

    # Apply formatting (on non-code text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _ITALIC_STAR.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDER.sub(r"<i>\1</i>", text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)

    # Restore code spans
    for i, span in enumerate(code_spans):
        text = text.replace(_CODE_PLACEHOLDER.format(i), span)

    return text


# ---------------------------------------------------------------------------
# Streaming: force-close unclosed tags
# ---------------------------------------------------------------------------

# Tags we might need to close if they are opened but not closed
_OPEN_CLOSE_TAGS = ["b", "i", "s", "code", "pre", "a", "blockquote"]


def _force_close_inline(html: str) -> str:
    """Ensure all opened HTML tags are closed (for partial streaming).

    Simple approach: count open vs close tags and append missing closes.
    """
    for tag in _OPEN_CLOSE_TAGS:
        open_count = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", html))
        close_count = len(re.findall(rf"</{tag}>", html))
        for _ in range(open_count - close_count):
            html += f"</{tag}>"

    return html
