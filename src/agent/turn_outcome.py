"""Typed outcomes produced by one agent turn."""

from __future__ import annotations

from dataclasses import dataclass

from src.memory.turn_selection import turn_failure_metadata


@dataclass(frozen=True)
class CompletedTurn:
    """A reply that satisfied the runtime completion checks."""

    content: str


@dataclass(frozen=True)
class FailedTurn:
    """A reply that records an explicitly failed runtime outcome."""

    content: str
    reason: str

    def message_metadata(self) -> dict[str, dict[str, str]]:
        """Return the persistent audit marker used by memory selection."""
        return turn_failure_metadata(self.reason)


type TurnOutcome = CompletedTurn | FailedTurn


def replace_turn_content(outcome: TurnOutcome, content: str) -> TurnOutcome:
    """Replace user-visible content without losing the outcome type."""
    if isinstance(outcome, FailedTurn):
        return FailedTurn(content=content, reason=outcome.reason)
    return CompletedTurn(content=content)
