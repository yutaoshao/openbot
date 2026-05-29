"""Structured tool effects used by the agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_VALIDATION_ERROR = "validation_error"
STATUS_MISSING_DEPENDENCY = "missing_dependency"

EFFECT_NONE = "none"


@dataclass(frozen=True)
class ToolEffect:
    """Typed fact emitted by a tool for harness-level verification."""

    action: str
    status: str = STATUS_COMPLETED
    effect: str = EFFECT_NONE
    target_type: str = ""
    target: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable record."""
        payload: dict[str, Any] = {
            "action": self.action,
            "status": self.status,
            "effect": self.effect,
        }
        if self.target_type:
            payload["target_type"] = self.target_type
        if self.target:
            payload["target"] = self.target
        if self.details:
            payload["details"] = _json_safe(self.details)
        if self.name:
            payload["name"] = self.name
        if self.summary:
            payload["summary"] = self.summary
        return payload

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ToolEffect:
        """Build an effect from a serialized record."""
        details = value.get("details")
        return cls(
            action=str(value.get("action") or ""),
            status=str(value.get("status") or STATUS_ERROR),
            effect=str(value.get("effect") or EFFECT_NONE),
            target_type=str(value.get("target_type") or ""),
            target=str(value.get("target") or ""),
            details=dict(details) if isinstance(details, dict) else {},
            name=str(value.get("name") or ""),
            summary=str(value.get("summary") or ""),
        )


def tool_effect(
    action: str,
    effect: str,
    *,
    status: str = STATUS_COMPLETED,
    target_type: str = "",
    target: str = "",
    name: str = "",
    summary: str = "",
    **details: Any,
) -> ToolEffect:
    """Create a structured tool effect with optional details."""
    return ToolEffect(
        action=action,
        status=status,
        effect=effect,
        target_type=target_type,
        target=target,
        details=details,
        name=name,
        summary=summary,
    )


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, tuple):
            safe[key] = list(item)
        else:
            safe[key] = item
    return safe
