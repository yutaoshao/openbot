from __future__ import annotations

from src.channels.markdown import md_to_telegram_html


def test_partial_mode_force_closes_unclosed_code_fence() -> None:
    text = "```python\nprint('hi')"

    html = md_to_telegram_html(text, partial=True)

    assert html.startswith('<pre><code class="language-python">')
    assert html.endswith("</code></pre>")


def test_markdown_link_and_bold_conversion() -> None:
    text = "**OpenBot** docs: [todo](https://example.com)"

    html = md_to_telegram_html(text, partial=False)

    assert "<b>OpenBot</b>" in html
    assert '<a href="https://example.com">todo</a>' in html


def test_table_renders_as_pre_block() -> None:
    text = "| Name  | Age |\n|-------|-----|\n| Alice | 30  |\n| Bob   | 25  |"

    html = md_to_telegram_html(text, partial=False)

    assert "<pre>" in html
    assert "</pre>" in html
    assert "Alice" in html
    assert "Bob" in html
    # Raw markdown separator (|---|) should NOT appear in output
    assert "|" not in html


def test_table_column_alignment() -> None:
    text = "| Short | LongHeader |\n|-------|------------|\n| A     | B          |"

    html = md_to_telegram_html(text, partial=False)

    # Should be in a pre block
    assert "<pre>" in html
    # Header and data should both be present
    assert "Short" in html
    assert "LongHeader" in html


def test_table_followed_by_text() -> None:
    text = "| X | Y |\n|---|---|\n| 1 | 2 |\n\nRegular text after table"

    html = md_to_telegram_html(text, partial=False)

    assert "<pre>" in html
    assert "Regular text after table" in html


def test_long_telegram_table_renders_as_field_list() -> None:
    text = (
        "| 层次 | 机制 | 能 |\n"
        "|---|---|---|\n"
        '| 记住"不喜欢emoji"吗 | Working Memory、`pin()` 和 `set_protected()` | '
        "只在当前会话有效，会话结束就丢了 |\n"
        "| 压缩前提取 | 压缩时 LLM 提取关键信息到 semantic_memory，但提取是随机的 | "
        "取决于 LLM 觉不觉得“不喜欢 emoji”是需要记住的 |"
    )

    html = md_to_telegram_html(text, partial=False)

    assert "<pre>" not in html
    assert "<b>记住&quot;不喜欢emoji&quot;吗</b>" in html
    assert "机制：Working Memory、<code>pin()</code> 和 <code>set_protected()</code>" in html
    assert "能：只在当前会话有效，会话结束就丢了" in html
