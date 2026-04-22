"""Tool hook framework for harness-level enforcement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.agent.state import TaskState
    from src.tools.registry import ToolResult


@dataclass
class PreToolHookResult:
    """Instructions produced before a tool call executes."""

    override_args: dict[str, object] | None = None
    feedback: list[str] = field(default_factory=list)


@dataclass
class PostToolHookResult:
    """Feedback and state changes produced after a tool call."""

    feedback: list[str] = field(default_factory=list)
    activated_tools: list[str] = field(default_factory=list)


class ToolHook(Protocol):
    """Protocol implemented by harness hooks."""

    async def before_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        task_state: TaskState | None,
    ) -> PreToolHookResult: ...

    async def after_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        result: ToolResult,
        task_state: TaskState | None,
    ) -> PostToolHookResult: ...


class ToolHookManager:
    """Dispatch tool hooks and merge their outputs."""

    def __init__(self, hooks: Iterable[ToolHook] | None = None) -> None:
        self._hooks = list(hooks or [])

    async def before_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        task_state: TaskState | None,
    ) -> PreToolHookResult:
        combined = PreToolHookResult()
        for hook in self._hooks:
            result = await hook.before_execute(tool_name, arguments, task_state)
            if result.override_args is not None:
                combined.override_args = dict(result.override_args)
            combined.feedback.extend(result.feedback)
        return combined

    async def after_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        result: ToolResult,
        task_state: TaskState | None,
    ) -> PostToolHookResult:
        combined = PostToolHookResult()
        for hook in self._hooks:
            hook_result = await hook.after_execute(
                tool_name,
                arguments,
                result,
                task_state,
            )
            combined.feedback.extend(hook_result.feedback)
            combined.activated_tools.extend(hook_result.activated_tools)
        return combined


class ToolSearchActivationHook:
    """Activate deferred tools exposed by the tool_search result."""

    async def before_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        task_state: TaskState | None,
    ) -> PreToolHookResult:
        return PreToolHookResult()

    async def after_execute(
        self,
        tool_name: str,
        arguments: dict[str, object],
        result: ToolResult,
        task_state: TaskState | None,
    ) -> PostToolHookResult:
        if tool_name != "tool_search":
            return PostToolHookResult()
        activated = result.metadata.get("activate_tools") or []
        if not isinstance(activated, list):
            activated = []
        feedback = []
        if activated:
            tool_list = ", ".join(str(item) for item in activated)
            feedback.append(f"Activated deferred tools: {tool_list}")
        return PostToolHookResult(
            feedback=feedback,
            activated_tools=[str(item) for item in activated],
        )
