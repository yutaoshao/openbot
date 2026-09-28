"""Tool execution helpers for the main Agent."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.tools.effects import EFFECT_NONE, STATUS_ERROR, STATUS_TIMEOUT, tool_effect
from src.tools.registry import ToolResult
from src.tools.runtime import ToolExecutionContext, tool_execution_context

logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.agent.state import TaskState
    from src.core.config import AgentConfig
    from src.tools.hooks import ToolHookManager
    from src.tools.registry import ToolRegistry


def summarize_tool_result(content: str) -> str:
    """Collapse verbose tool output into a compact task-state summary."""
    cleaned = " ".join(content.strip().split())
    return cleaned[:180] if cleaned else "(no output)"


async def execute_tool_call(
    registry: ToolRegistry | None,
    config: AgentConfig,
    hooks: ToolHookManager,
    name: str,
    arguments: dict[str, Any],
    *,
    conversation_id: str,
    platform: str,
    task_state: TaskState | None = None,
    timeout_override: float | None = None,
) -> ToolResult:
    """Execute a single tool call by name."""
    if registry is None:
        return ToolResult(content="No tools available", is_error=True)

    tool = registry.get(name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)

    configured_timeout = config.tool_timeout if config.tool_timeout > 0 else None
    timeout_candidates = [
        timeout
        for timeout in (configured_timeout, timeout_override)
        if timeout is not None and timeout > 0
    ]
    effective_timeout = min(timeout_candidates) if timeout_candidates else None

    try:
        pre_result = await hooks.before_execute(name, arguments, task_state)
        effective_arguments = dict(pre_result.override_args or arguments)
        tool_result = await _run_tool(
            tool,
            effective_arguments,
            effective_timeout,
            conversation_id,
            platform,
        )
        post_result = await hooks.after_execute(
            name,
            effective_arguments,
            tool_result,
            task_state,
        )
        return _apply_hook_results(tool_result, pre_result, post_result)
    except TimeoutError:
        return _timeout_result(name, effective_timeout)
    except Exception as exc:
        return _exception_result(name, exc)


async def _run_tool(
    tool: Any,
    arguments: dict[str, Any],
    timeout: float | None,
    conversation_id: str,
    platform: str,
) -> ToolResult:
    context = ToolExecutionContext(conversation_id=conversation_id, platform=platform)
    with tool_execution_context(context):
        if timeout is None:
            return await tool.execute(arguments)
        return await asyncio.wait_for(tool.execute(arguments), timeout=timeout)


def _apply_hook_results(tool_result: ToolResult, pre_result: Any, post_result: Any) -> ToolResult:
    metadata = dict(tool_result.metadata)
    combined_feedback = [*pre_result.feedback, *post_result.feedback]
    if combined_feedback:
        feedback_text = "\n".join(combined_feedback)
        tool_result.content = f"{tool_result.content}\n\nHarness feedback:\n{feedback_text}".strip()
        metadata["hook_feedback"] = combined_feedback
    if post_result.activated_tools:
        metadata["activated_tools"] = list(post_result.activated_tools)
    tool_result.metadata = metadata
    return tool_result


def _timeout_result(name: str, timeout: float | None) -> ToolResult:
    timeout_text = f"{timeout:.2f}" if timeout is not None else "unknown"
    logger.warning(
        "tool_timeout",
        surface="operational",
        tool=name,
        timeout_s=round(timeout or 0.0, 3),
    )
    return ToolResult(
        content=f"Tool '{name}' timed out after {timeout_text}s",
        is_error=True,
        effects=(_tool_effect(name, STATUS_TIMEOUT),),
    )


def _exception_result(name: str, exc: Exception) -> ToolResult:
    logger.exception(
        "tool_called",
        surface="operational",
        tool=name,
        status="exception",
        error=str(exc),
    )
    return ToolResult(
        content=f"Tool error: {exc}",
        is_error=True,
        effects=(_tool_effect(name, STATUS_ERROR),),
    )


def _tool_effect(name: str, status: str):
    return tool_effect(
        f"{name}.execute",
        EFFECT_NONE,
        status=status,
        target_type="tool",
        target=name,
        name=name,
    )
