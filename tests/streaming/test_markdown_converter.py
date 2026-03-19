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
