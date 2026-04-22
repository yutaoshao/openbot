"""Structured task state tracked per conversation."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_TOOL_EVENTS = 8
MAX_OPEN_ITEMS = 4
MAX_COMPLETED_ITEMS = 4
_GENERIC_DONE_PHRASES = (
    "done",
    "completed",
    "分析完成",
    "已完成",
)


@dataclass
class ToolEvent:
    """A concise record of one tool execution."""

    tool_name: str
    summary: str
    is_error: bool = False


@dataclass
class TaskState:
    """Conversation-scoped structured state for the current objective."""

    objective: str = ""
    status: str = "active"
    open_items: list[str] = field(default_factory=list)
    completed_items: list[str] = field(default_factory=list)
    activated_tools: set[str] = field(default_factory=set)
    tool_events: list[ToolEvent] = field(default_factory=list)
    requires_follow_up: bool = False

    def note_user_input(self, text: str) -> None:
        """Refresh the active objective and open items from user input."""
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        self.objective = cleaned
        self.status = "active"
        self.requires_follow_up = True
        if cleaned not in self.open_items:
            self.open_items.insert(0, cleaned)
        self.open_items = self.open_items[:MAX_OPEN_ITEMS]

    def record_tool_event(
        self,
        tool_name: str,
        summary: str,
        *,
        is_error: bool,
        activated_tools: list[str] | None = None,
    ) -> None:
        """Append a summarized tool event and capture any activations."""
        event = ToolEvent(
            tool_name=tool_name,
            summary=summary.strip(),
            is_error=is_error,
        )
        self.tool_events.append(event)
        self.tool_events = self.tool_events[-MAX_TOOL_EVENTS:]
        if activated_tools:
            self.activated_tools.update(activated_tools)
        self.requires_follow_up = True

    def note_assistant_reply(self, text: str) -> None:
        """Update completion state based on the final assistant reply."""
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return
        if self._looks_complete(cleaned):
            self.status = "completed"
            if self.objective:
                self._mark_completed(self.objective)
        self.requires_follow_up = False

    def protected_context(self) -> str:
        """Render task state as protected context for the model."""
        lines = ["Current Task State:"]
        lines.append(f"- Objective: {self.objective or 'Not set'}")
        lines.append(f"- Status: {self.status}")
        if self.open_items:
            lines.append("- Open items:")
            lines.extend(f"  - {item}" for item in self.open_items[:MAX_OPEN_ITEMS])
        if self.completed_items:
            lines.append("- Completed items:")
            lines.extend(
                f"  - {item}" for item in self.completed_items[:MAX_COMPLETED_ITEMS]
            )
        if self.activated_tools:
            activated = ", ".join(sorted(self.activated_tools))
            lines.append(f"- Activated tools: {activated}")
        if self.tool_events:
            lines.append("- Recent tool observations:")
            lines.extend(self._render_tool_events())
        return "\n".join(lines)

    def completion_summary(self) -> str:
        """Build a fallback summary when the model returns a vague completion."""
        lines = []
        if self.objective:
            lines.append(f"Objective: {self.objective}")
        if self.completed_items:
            lines.append("Completed:")
            lines.extend(f"- {item}" for item in self.completed_items[:MAX_COMPLETED_ITEMS])
        if self.tool_events:
            lines.append("Evidence:")
            for event in self.tool_events[-3:]:
                prefix = "error" if event.is_error else "ok"
                lines.append(f"- [{prefix}] {event.tool_name}: {event.summary}")
        return "\n".join(lines).strip()

    def _mark_completed(self, item: str) -> None:
        if item in self.open_items:
            self.open_items.remove(item)
        if item not in self.completed_items:
            self.completed_items.insert(0, item)
        self.completed_items = self.completed_items[:MAX_COMPLETED_ITEMS]

    def _render_tool_events(self) -> list[str]:
        rendered: list[str] = []
        for event in self.tool_events[-3:]:
            prefix = "error" if event.is_error else "ok"
            rendered.append(f"  - [{prefix}] {event.tool_name}: {event.summary}")
        return rendered

    @staticmethod
    def _looks_complete(text: str) -> bool:
        lowered = text.lower()
        if any(phrase in lowered for phrase in _GENERIC_DONE_PHRASES):
            return True
        return len(text) > 80
