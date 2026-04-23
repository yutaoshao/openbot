from __future__ import annotations

from src.memory.procedural.helpers import parse_preferences


def test_parse_preferences_extracts_json_array_from_wrapped_text() -> None:
    parsed = parse_preferences(
        """
        Here are the preferences I found:
        [
          {
            "category": "communication",
            "key": "preferred_language",
            "value": "reply in Chinese",
            "confidence": 0.9
          }
        ]
        """
    )

    assert parsed == [
        {
            "category": "communication",
            "key": "preferred_language",
            "value": "reply in Chinese",
            "confidence": 0.9,
        }
    ]


def test_parse_preferences_accepts_fenced_json_array() -> None:
    parsed = parse_preferences(
        """```json
        [
          {
            "category": "workflow",
            "key": "test_preference",
            "value": "prefer pytest",
            "confidence": 0.6
          }
        ]
        ```"""
    )

    assert parsed == [
        {
            "category": "workflow",
            "key": "test_preference",
            "value": "prefer pytest",
            "confidence": 0.6,
        }
    ]
