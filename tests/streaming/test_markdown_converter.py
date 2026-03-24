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
    text = (
        "| Name  | Age |\n"
        "|-------|-----|\n"
        "| Alice | 30  |\n"
        "| Bob   | 25  |"
    )

    html = md_to_telegram_html(text, partial=False)

    assert "<pre>" in html
    assert "</pre>" in html
    assert "Alice" in html
    assert "Bob" in html
    # Raw markdown separator (|---|) should NOT appear in output
    assert "|" not in html


def test_table_column_alignment() -> None:
    text = (
        "| Short | LongHeader |\n"
        "|-------|------------|\n"
        "| A     | B          |"
    )

    html = md_to_telegram_html(text, partial=False)

    # Should be in a pre block
    assert "<pre>" in html
    # Header and data should both be present
    assert "Short" in html
    assert "LongHeader" in html


def test_table_followed_by_text() -> None:
    text = (
        "| X | Y |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "\n"
        "Regular text after table"
    )

    html = md_to_telegram_html(text, partial=False)

    assert "<pre>" in html
    assert "Regular text after table" in html
