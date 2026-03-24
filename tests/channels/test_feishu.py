"""Tests for the Feishu adapter."""

from __future__ import annotations

from src.channels.adapters.feishu import FeishuAdapter


class TestStripMentions:
    def test_strips_user_mentions(self) -> None:
        assert FeishuAdapter._strip_mentions("@_user_1 hello") == "hello"

    def test_strips_all_mention(self) -> None:
        assert FeishuAdapter._strip_mentions("@_all check this") == "check this"

    def test_no_mention(self) -> None:
        assert FeishuAdapter._strip_mentions("plain text") == "plain text"

    def test_multiple_mentions(self) -> None:
        assert FeishuAdapter._strip_mentions("@_user_1 @_user_2 hi") == "hi"


class TestShouldUseCard:
    def test_plain_text_no_card(self) -> None:
        assert FeishuAdapter._should_use_card("just a simple reply") is False

    def test_code_block_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("here: ```code```") is True

    def test_bold_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("**important**") is True

    def test_table_triggers_card(self) -> None:
        assert FeishuAdapter._should_use_card("| col1 | col2 |") is True


class TestBuildCard:
    def test_card_structure(self) -> None:
        card = FeishuAdapter._build_card("hello world")
        assert "config" in card
        assert "elements" in card
        assert card["config"]["wide_screen_mode"] is True
        assert len(card["elements"]) == 1
        assert card["elements"][0]["tag"] == "div"
        assert card["elements"][0]["text"]["tag"] == "lark_md"
        assert card["elements"][0]["text"]["content"] == "hello world"
