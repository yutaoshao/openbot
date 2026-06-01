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
class ResourceRef:
    """Canonical identity for a resource touched by a tool or task contract."""

    kind: str
    canonical: str
    raw: str = ""
    ambiguity: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": self.kind,
            "canonical": self.canonical,
            "raw": self.raw,
        }
        if self.ambiguity:
            payload["ambiguity"] = list(self.ambiguity)
        if self.error:
            payload["error"] = self.error
        return payload

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ResourceRef:
        ambiguity = value.get("ambiguity")
        return cls(
            kind=str(value.get("kind") or ""),
            canonical=str(value.get("canonical") or ""),
            raw=str(value.get("raw") or ""),
            ambiguity=tuple(str(item) for item in ambiguity)
            if isinstance(ambiguity, list | tuple)
            else (),
            error=str(value.get("error") or ""),
        )


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
    resource: ResourceRef | None = None

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
        if self.resource is not None:
            payload["resource"] = self.resource.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ToolEffect:
        """Build an effect from a serialized record."""
        details = value.get("details")
        resource = value.get("resource")
        return cls(
            action=str(value.get("action") or ""),
            status=str(value.get("status") or STATUS_ERROR),
            effect=str(value.get("effect") or EFFECT_NONE),
            target_type=str(value.get("target_type") or ""),
            target=str(value.get("target") or ""),
            details=dict(details) if isinstance(details, dict) else {},
            name=str(value.get("name") or ""),
            summary=str(value.get("summary") or ""),
            resource=ResourceRef.from_mapping(resource) if isinstance(resource, dict) else None,
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
    resource: ResourceRef | None = None,
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
        resource=resource or _resource_from_target(target_type, target),
    )


def _resource_from_target(target_type: str, target: str) -> ResourceRef | None:
    if not target_type:
        return None
    kind = _resource_kind(target_type)
    return ResourceRef(kind=kind, canonical=target, raw=target)


def _resource_kind(target_type: str) -> str:
    if target_type in {"file", "path"}:
        return "file"
    if target_type in {"cwd", "runtime"}:
        return "command"
    if target_type == "query" and target_type:
        return "query"
    return target_type


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, tuple):
            safe[key] = list(item)
        else:
            safe[key] = item
    return safe
